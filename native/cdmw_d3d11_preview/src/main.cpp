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

struct Args {
    std::wstring backend = L"d3d11";
    fs::path preview_package;
    fs::path status_file;
    std::string theme_background = "#080b0e";
    std::string theme_text = "#c5ced8";
    uintptr_t parent_hwnd = 0;
    bool self_test = false;
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
    float height_scale_hint = 0.0f;
    float emissive_intensity = 0.0f;
    float emissive_color[3] = {0.35f, 0.68f, 1.0f};
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
    int material_contract_schema = 0;
    int material_channel_contract_schema = 0;
    int texture_quality_schema = 0;
    int cloth_runtime_schema = 0;
    std::string render_diagnostic_mode;
    std::string lighting_preset;
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

static int diagnostic_mode_code(const std::string& value) {
    std::string mode = value;
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (mode == "lit" || mode == "final_lit" || mode == "final") return 0;
    if (mode == "base" || mode == "base_texture" || mode == "texture" || mode == "albedo" ||
        mode == "albedo_base_only" || mode == "base_only" ||
        mode == "base_direct" || mode == "base_no_tint" || mode == "base_color" || mode == "texture_probe") return 1;
    if (mode == "uv" || mode == "uv_checker" || mode == "checker") return 2;
    if (mode == "alpha" || mode == "opacity" || mode == "base_alpha") return 3;
    if (mode == "material_slot" || mode == "material_slot_id" || mode == "slot" || mode == "part_id") return 4;
    if (mode == "normal" || mode == "normals" || mode == "normal_raw") return 5;
    if (mode == "support" || mode == "support_maps" || mode == "pbr" ||
        mode == "material_raw" || mode == "height_raw" || mode == "height_calibrated" ||
        mode == "height_depth" || mode == "material_response" || mode == "metal_shine" ||
        mode == "roughness_response") return 6;
    if (mode == "layer_mask" || mode == "layer_masks" || mode == "mask" || mode == "detail_mask" ||
        mode == "masked_layer_contribution" || mode == "masked_layers") return 7;
    if (mode == "metalness" || mode == "metallic") return 8;
    if (mode == "roughness") return 9;
    if (mode == "specular_gloss" || mode == "specular_glossiness" || mode == "specular" || mode == "gloss") return 10;
    return 0;
}

static std::string wide_to_utf8(const std::wstring& text) {
    if (text.empty()) return "";
    int needed = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "";
    std::string output(static_cast<size_t>(needed), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed, nullptr, nullptr);
    return output;
}

static std::wstring utf8_to_wide(const std::string& text) {
    if (text.empty()) return L"";
    int needed = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    if (needed <= 0) return L"";
    std::wstring output(static_cast<size_t>(needed), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), output.data(), needed);
    return output;
}

static std::string filename_from_path(const std::wstring& path) {
    if (path.empty()) return "";
    return wide_to_utf8(fs::path(path).filename().wstring());
}

static std::string json_escape(const std::string& text) {
    std::ostringstream out;
    for (char ch : text) {
        switch (ch) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default: out << ch; break;
        }
    }
    return out.str();
}

static std::string json_unescape(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (size_t i = 0; i < text.size(); ++i) {
        char ch = text[i];
        if (ch != '\\' || i + 1 >= text.size()) {
            out.push_back(ch);
            continue;
        }
        char next = text[++i];
        switch (next) {
        case '\\': out.push_back('\\'); break;
        case '"': out.push_back('"'); break;
        case 'n': out.push_back('\n'); break;
        case 'r': out.push_back('\r'); break;
        case 't': out.push_back('\t'); break;
        default: out.push_back(next); break;
        }
    }
    return out;
}

static std::string read_text(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

static std::vector<uint8_t> read_binary(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
}

static std::vector<uint8_t> read_binary_range(const fs::path& path, std::uint64_t offset, std::uint64_t size) {
    if (size == 0u) return {};
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return {};
    stream.seekg(0, std::ios::end);
    const std::streamoff end = static_cast<std::streamoff>(stream.tellg());
    if (end <= 0) return {};
    const std::uint64_t file_size = static_cast<std::uint64_t>(end);
    if (offset >= file_size) return {};
    const std::uint64_t available = file_size - offset;
    const std::uint64_t read_size = std::min(size, available);
    std::vector<uint8_t> data(static_cast<size_t>(read_size));
    stream.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
    stream.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    data.resize(static_cast<size_t>(std::max<std::streamsize>(0, stream.gcount())));
    return data;
}

static bool write_status(const fs::path& path, const std::string& payload) {
    if (path.empty()) return true;
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    fs::path temp = path;
    temp += L".tmp";
    std::ofstream stream(temp, std::ios::binary);
    if (!stream) return false;
    stream.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    stream.close();
    fs::rename(temp, path, ec);
    if (ec) {
        fs::copy_file(temp, path, fs::copy_options::overwrite_existing, ec);
        fs::remove(temp, ec);
    }
    return true;
}

static std::string write_i32_temp_descriptor_json(const std::vector<int>& values, int components, const wchar_t* label) {
    if (values.empty() || components <= 0 || values.size() % static_cast<size_t>(components) != 0) return std::string();
    std::error_code ec;
    const fs::path root = fs::temp_directory_path(ec);
    if (ec) return std::string();
    static unsigned long long counter = 0;
    const unsigned long long tick = static_cast<unsigned long long>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::wstringstream name;
    name << L"cdmw_mesh_preview_delta_d3d11_" << (label ? label : L"selection")
         << L"_" << GetCurrentProcessId() << L"_" << tick << L"_" << counter++ << L".bin";
    const fs::path path = root / name.str();
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return std::string();
        for (int value : values) {
            const std::int32_t raw = static_cast<std::int32_t>(value);
            output.write(reinterpret_cast<const char*>(&raw), static_cast<std::streamsize>(sizeof(raw)));
        }
        if (!output) {
            fs::remove(path, ec);
            return std::string();
        }
    }
    std::ostringstream out;
    out << "{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
        << "\",\"count\":" << (values.size() / static_cast<size_t>(components))
        << ",\"components\":" << components
        << ",\"type\":\"i32\",\"delete_after\":true}";
    return out.str();
}

static std::string write_f32_temp_descriptor_json(const std::vector<float>& values, int components, const wchar_t* label) {
    if (values.empty() || components <= 0 || values.size() % static_cast<size_t>(components) != 0) return std::string();
    std::error_code ec;
    const fs::path root = fs::temp_directory_path(ec);
    if (ec) return std::string();
    static unsigned long long counter = 0;
    const unsigned long long tick = static_cast<unsigned long long>(
        std::chrono::steady_clock::now().time_since_epoch().count());
    std::wstringstream name;
    name << L"cdmw_mesh_preview_delta_d3d11_" << (label ? label : L"values")
         << L"_" << GetCurrentProcessId() << L"_" << tick << L"_" << counter++ << L".bin";
    const fs::path path = root / name.str();
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return std::string();
        for (float value : values) {
            output.write(reinterpret_cast<const char*>(&value), static_cast<std::streamsize>(sizeof(value)));
        }
        if (!output) {
            fs::remove(path, ec);
            return std::string();
        }
    }
    std::ostringstream out;
    out << "{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
        << "\",\"count\":" << (values.size() / static_cast<size_t>(components))
        << ",\"components\":" << components
        << ",\"type\":\"f32\",\"delete_after\":true}";
    return out.str();
}

static bool contiguous_i32_range(const std::vector<int>& values, int& start) {
    if (values.empty()) return false;
    start = values.front();
    if (start < 0) return false;
    for (size_t index = 0; index < values.size(); ++index) {
        if (values[index] != start + static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

static void write_i32_range_or_descriptor_json(
    std::ostream& out,
    const std::vector<int>& values,
    const char* json_name,
    const char* binary_name,
    const char* start_name,
    const char* count_name,
    const wchar_t* label
) {
    int range_start = -1;
    if (contiguous_i32_range(values, range_start)) {
        out << ",\"" << start_name << "\":" << range_start
            << ",\"" << count_name << "\":" << values.size();
        return;
    }
    const std::string descriptor = write_i32_temp_descriptor_json(values, 1, label);
    if (!values.empty() && !descriptor.empty()) {
        out << ",\"" << binary_name << "\":" << descriptor;
        return;
    }
    out << ",\"" << json_name << "\":[";
    for (size_t index = 0; index < values.size(); ++index) {
        if (index) out << ",";
        out << values[index];
    }
    out << "]";
}

static Args parse_args(int argc, wchar_t** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::wstring key = argv[i];
        auto next = [&]() -> std::wstring {
            if (i + 1 >= argc) return L"";
            return argv[++i];
        };
        if (key == L"--self-test") args.self_test = true;
        else if (key == L"--backend") args.backend = next();
        else if (key == L"--preview-package") args.preview_package = next();
        else if (key == L"--status-file") args.status_file = next();
        else if (key == L"--theme-background") args.theme_background = wide_to_utf8(next());
        else if (key == L"--theme-text") args.theme_text = wide_to_utf8(next());
        else if (key == L"--crash-dir") args.crash_dir = next();
        else if (key == L"--diagnostic-log") args.diagnostic_log = next();
        else if (key == L"--parent-hwnd") {
            std::wstring value = next();
            wchar_t* end = nullptr;
            args.parent_hwnd = static_cast<uintptr_t>(_wcstoui64(value.c_str(), &end, 0));
        }
    }
    return args;
}

static std::string json_string_field(const std::string& object, const std::string& name, const std::string& fallback = "") {
    std::regex pattern("\"" + name + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    return json_unescape(match[1].str());
}

static int json_int_field(const std::string& object, const std::string& name, int fallback = 0) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(-?\\d+)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return std::stoi(match[1].str());
    } catch (...) {
        return fallback;
    }
}

static std::uint64_t json_uint64_field(const std::string& object, const std::string& name, std::uint64_t fallback = 0) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(\\d+)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return static_cast<std::uint64_t>(std::stoull(match[1].str()));
    } catch (...) {
        return fallback;
    }
}

static bool json_bool_field(const std::string& object, const std::string& name, bool fallback = false) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(true|false)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    return match[1].str() == "true";
}

static float json_float_field(const std::string& object, const std::string& name, float fallback = 0.0f) {
    std::regex pattern("\"" + name + "\"\\s*:\\s*(-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?)");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return fallback;
    try {
        return std::stof(match[1].str());
    } catch (...) {
        return fallback;
    }
}

static bool json_has_field(const std::string& object, const std::string& name) {
    std::regex pattern("\"" + name + "\"\\s*:");
    return std::regex_search(object, pattern);
}

static std::vector<std::string> objects_with_key(const std::string& text, const std::string& key) {
    std::vector<std::string> objects;
    std::string needle = "\"" + key + "\"";
    size_t search = 0;
    while (true) {
        size_t key_pos = text.find(needle, search);
        if (key_pos == std::string::npos) break;
        size_t start = text.rfind('{', key_pos);
        if (start == std::string::npos) break;
        int depth = 0;
        bool in_string = false;
        bool escaped = false;
        size_t end = std::string::npos;
        for (size_t i = start; i < text.size(); ++i) {
            char ch = text[i];
            if (escaped) {
                escaped = false;
                continue;
            }
            if (ch == '\\' && in_string) {
                escaped = true;
                continue;
            }
            if (ch == '"') {
                in_string = !in_string;
                continue;
            }
            if (in_string) continue;
            if (ch == '{') ++depth;
            else if (ch == '}') {
                --depth;
                if (depth == 0) {
                    end = i;
                    break;
                }
            }
        }
        if (end == std::string::npos) break;
        objects.push_back(text.substr(start, end - start + 1));
        search = end + 1;
    }
    return objects;
}

static std::wstring absolute_from_manifest_path(const fs::path& package_dir, const std::string& value) {
    if (value.empty()) return L"";
    fs::path path = utf8_to_wide(value);
    if (path.is_relative()) path = package_dir / path;
    return path.wstring();
}

static std::string json_object_field(const std::string& object, const std::string& name);

static std::wstring dds_slot_source(const std::string& object, const std::string& slot) {
    const std::string descriptor = json_object_field(object, slot);
    if (descriptor.empty()) return L"";
    if (!json_bool_field(descriptor, "available", true)) return L"";
    if (!json_bool_field(descriptor, "direct_upload_candidate", true)) return L"";
    return utf8_to_wide(json_string_field(descriptor, "source_path"));
}

static std::wstring texture_slot_relative(const fs::path& package_dir, const std::string& object, const std::string& slot) {
    std::regex textures_pattern("\"textures\"\\s*:\\s*\\{([^{}]*)\\}");
    std::smatch textures_match;
    if (!std::regex_search(object, textures_match, textures_pattern)) return L"";
    std::string textures_object = textures_match[1].str();
    return absolute_from_manifest_path(package_dir, json_string_field(textures_object, slot));
}

static std::vector<std::string> json_string_array_field(const std::string& object, const std::string& name) {
    std::vector<std::string> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("\"((?:\\\\.|[^\"])*)\"");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        values.push_back(json_unescape((*it)[1].str()));
    }
    return values;
}

static std::vector<int> json_int_array_field(const std::string& object, const std::string& name) {
    std::vector<int> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("-?\\d+");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stoi(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::vector<int> json_int_values_in_array_field(const std::string& object, const std::string& name) {
    std::vector<int> values;
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return values;
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return values;
    size_t array_start = object.find('[', colon + 1);
    if (array_start == std::string::npos) return values;
    bool in_string = false;
    bool escaped = false;
    int depth = 0;
    size_t array_end = std::string::npos;
    for (size_t i = array_start; i < object.size(); ++i) {
        const char ch = object[i];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '[') ++depth;
        else if (ch == ']') {
            --depth;
            if (depth == 0) {
                array_end = i;
                break;
            }
        }
    }
    if (array_end == std::string::npos || array_end <= array_start) return values;
    const std::string array_text = object.substr(array_start + 1u, array_end - array_start - 1u);
    std::regex item_pattern("-?\\d+");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stoi(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::vector<float> json_float_array_field(const std::string& object, const std::string& name) {
    std::vector<float> values;
    std::regex pattern("\"" + name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return values;
    std::string array_text = match[1].str();
    std::regex item_pattern("-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    auto begin = std::sregex_iterator(array_text.begin(), array_text.end(), item_pattern);
    auto end = std::sregex_iterator();
    for (auto it = begin; it != end; ++it) {
        try {
            values.push_back(std::stof(it->str()));
        } catch (...) {
        }
    }
    return values;
}

static std::string json_object_field(const std::string& object, const std::string& name) {
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return "";
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return "";
    size_t object_start = object.find('{', colon + 1);
    if (object_start == std::string::npos) return "";
    bool in_string = false;
    bool escaped = false;
    int depth = 0;
    for (size_t i = object_start; i < object.size(); ++i) {
        const char ch = object[i];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '{') {
            ++depth;
            continue;
        }
        if (ch == '}') {
            --depth;
            if (depth == 0) {
                return object.substr(object_start + 1, i - object_start - 1);
            }
        }
    }
    return "";
}

static std::string json_binary_payload_path_field(const std::string& object, const std::string& name) {
    const std::string descriptor = json_object_field(object, name);
    if (!descriptor.empty()) {
        return json_string_field(descriptor, "path");
    }
    return json_string_field(object, name);
}

static bool json_binary_payload_delete_after_field(const std::string& object, const std::string& name) {
    const std::string descriptor = json_object_field(object, name);
    return !descriptor.empty() && json_bool_field(descriptor, "delete_after", false);
}

static void delete_json_binary_payload_if_requested(const std::string& object, const std::string& name) {
    if (!json_binary_payload_delete_after_field(object, name)) return;
    const std::string path_text = json_binary_payload_path_field(object, name);
    if (path_text.empty()) return;
    const fs::path path = utf8_to_wide(path_text);
    const std::wstring filename = path.filename().wstring();
    if (filename.rfind(L"cdmw_mesh_preview_delta_", 0) != 0) return;
    std::error_code ec;
    fs::remove(path, ec);
}

static std::vector<uint8_t> json_binary_payload_bytes_field(
    const std::string& object,
    const std::string& name,
    size_t element_size
) {
    const std::string path_text = json_binary_payload_path_field(object, name);
    if (path_text.empty()) return {};
    std::vector<uint8_t> bytes = read_binary(utf8_to_wide(path_text));
    delete_json_binary_payload_if_requested(object, name);
    if (element_size == 0u || bytes.empty() || bytes.size() % element_size != 0u) return {};
    return bytes;
}

static std::vector<float> json_f64_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name,
    int components
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(
        object,
        binary_name,
        sizeof(double) * static_cast<size_t>(std::max(1, components)));
    if (bytes.empty()) return json_float_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(double);
    std::vector<float> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        double raw = 0.0;
        std::memcpy(&raw, bytes.data() + index * sizeof(double), sizeof(double));
        if (!std::isfinite(raw)) return {};
        values.push_back(static_cast<float>(raw));
    }
    return values;
}

static std::vector<int> json_i32_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(object, binary_name, sizeof(std::int32_t));
    if (bytes.empty()) return json_int_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<int> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        std::int32_t raw = 0;
        std::memcpy(&raw, bytes.data() + index * sizeof(std::int32_t), sizeof(std::int32_t));
        values.push_back(static_cast<int>(raw));
    }
    return values;
}

static std::vector<int> json_i32_range_or_array_or_json_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name,
    const std::string& start_name,
    const std::string& count_name
) {
    std::vector<int> values = json_i32_array_or_json_field(object, binary_name, json_name);
    if (!values.empty()) return values;
    const int start = json_int_field(object, start_name, -1);
    const int count = json_int_field(object, count_name, 0);
    if (start < 0 || count <= 0) return values;
    values.reserve(static_cast<size_t>(count));
    for (int offset = 0; offset < count; ++offset) {
        values.push_back(start + offset);
    }
    return values;
}

static std::vector<int> json_i32_array_or_json_values_field(
    const std::string& object,
    const std::string& binary_name,
    const std::string& json_name
) {
    const std::vector<uint8_t> bytes = json_binary_payload_bytes_field(object, binary_name, sizeof(std::int32_t));
    if (bytes.empty()) return json_int_values_in_array_field(object, json_name);
    const size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<int> values;
    values.reserve(count);
    for (size_t index = 0; index < count; ++index) {
        std::int32_t raw = 0;
        std::memcpy(&raw, bytes.data() + index * sizeof(std::int32_t), sizeof(std::int32_t));
        values.push_back(static_cast<int>(raw));
    }
    return values;
}

static bool self_test_i32_descriptor_reader() {
    std::error_code ec;
    const fs::path path = fs::temp_directory_path(ec) / L"cdmw_mesh_preview_delta_self_test_selection.bin";
    if (ec) return false;
    {
        std::ofstream output(path, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        const std::int32_t values[3] = {2, 4, 6};
        output.write(reinterpret_cast<const char*>(values), static_cast<std::streamsize>(sizeof(values)));
        if (!output) return false;
    }
    std::ostringstream payload;
    payload << "{\"source_vertex_indices_binary\":{\"path\":\"" << json_escape(wide_to_utf8(path.wstring()))
            << "\",\"count\":3,\"components\":1,\"type\":\"i32\",\"delete_after\":true}}";
    const std::vector<int> parsed = json_i32_array_or_json_field(payload.str(), "source_vertex_indices_binary", "source_vertex_indices");
    const std::vector<int> parsed_range = json_i32_range_or_array_or_json_field(
        "{\"source_vertex_start\":5,\"source_vertex_count\":3}",
        "source_vertex_indices_binary",
        "source_vertex_indices",
        "source_vertex_start",
        "source_vertex_count");
    const bool removed = !fs::exists(path, ec);
    const std::string edge_descriptor = write_i32_temp_descriptor_json(std::vector<int>({1, 2, 2, 3}), 2, L"self_test_edges");
    if (edge_descriptor.empty()) return false;
    const std::string edge_payload = std::string("{\"source_edges_binary\":") + edge_descriptor + "}";
    const std::vector<int> parsed_edges = json_i32_array_or_json_values_field(edge_payload, "source_edges_binary", "source_edges");
    const std::string edge_path = json_string_field(edge_descriptor, "path");
    const bool edge_removed = edge_path.empty() || !fs::exists(utf8_to_wide(edge_path), ec);
    const std::string weight_descriptor = write_f32_temp_descriptor_json(std::vector<float>({0.25f, 1.0f}), 1, L"self_test_weights");
    if (weight_descriptor.empty()) return false;
    const std::string weight_payload = std::string("{\"source_vertex_weights_binary\":") + weight_descriptor + "}";
    const std::vector<uint8_t> weight_bytes = json_binary_payload_bytes_field(weight_payload, "source_vertex_weights_binary", sizeof(float));
    std::vector<float> parsed_weights;
    for (size_t index = 0; index + sizeof(float) <= weight_bytes.size(); index += sizeof(float)) {
        float raw = 0.0f;
        std::memcpy(&raw, weight_bytes.data() + index, sizeof(float));
        parsed_weights.push_back(raw);
    }
    const std::string weight_path = json_string_field(weight_descriptor, "path");
    const bool weight_removed = weight_path.empty() || !fs::exists(utf8_to_wide(weight_path), ec);
    return parsed == std::vector<int>({2, 4, 6})
        && parsed_range == std::vector<int>({5, 6, 7})
        && removed
        && parsed_edges == std::vector<int>({1, 2, 2, 3})
        && edge_removed
        && parsed_weights == std::vector<float>({0.25f, 1.0f})
        && weight_removed;
}

static std::vector<std::string> json_object_array_field(const std::string& object, const std::string& name) {
    std::vector<std::string> values;
    const std::string marker = "\"" + name + "\"";
    size_t name_pos = object.find(marker);
    if (name_pos == std::string::npos) return values;
    size_t colon = object.find(':', name_pos + marker.size());
    if (colon == std::string::npos) return values;
    size_t array_start = object.find('[', colon + 1);
    if (array_start == std::string::npos) return values;
    bool in_string = false;
    bool escaped = false;
    int array_depth = 0;
    int object_depth = 0;
    size_t item_start = std::string::npos;
    for (size_t i = array_start; i < object.size(); ++i) {
        const char ch = object[i];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            in_string = !in_string;
            continue;
        }
        if (in_string) continue;
        if (ch == '[') {
            ++array_depth;
            continue;
        }
        if (ch == ']') {
            --array_depth;
            if (array_depth <= 0) break;
            continue;
        }
        if (array_depth != 1) continue;
        if (ch == '{') {
            if (object_depth == 0) item_start = i;
            ++object_depth;
            continue;
        }
        if (ch == '}' && object_depth > 0) {
            --object_depth;
            if (object_depth == 0 && item_start != std::string::npos) {
                values.push_back(object.substr(item_start, i - item_start + 1));
                item_start = std::string::npos;
            }
        }
    }
    return values;
}

static std::string lower_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

static std::string normalize_display_mode(std::string value, const std::string& fallback = "replacement_only") {
    value = lower_copy(std::move(value));
    if (value == "side_by_side" || value == "overlay" || value == "replacement_only" || value == "original_only") {
        return value;
    }
    return fallback == "side_by_side" || fallback == "overlay" || fallback == "replacement_only" || fallback == "original_only" ? fallback : "replacement_only";
}

static std::string parse_display_mode(const std::string& manifest, const std::string& fallback = "replacement_only") {
    return normalize_display_mode(json_string_field(manifest, "display_mode", fallback), fallback);
}

static bool contains_text(const std::string& haystack, const std::string& needle) {
    return haystack.find(needle) != std::string::npos;
}

static bool looks_like_path_suffix(const std::string& source_path, const std::string& suffix) {
    std::string lower = lower_copy(source_path);
    size_t slash = lower.find_last_of("/\\");
    std::string name = slash == std::string::npos ? lower : lower.substr(slash + 1);
    if (name.size() >= suffix.size() + 4 && name.ends_with(suffix + ".dds")) return true;
    if (name.size() >= suffix.size() && name.ends_with(suffix)) return true;
    return false;
}

static int material_dds_candidate_score(const std::string& object, const std::string& role) {
    std::string source_path = json_string_field(object, "source_path");
    if (source_path.empty()) return -1000;
    if (!json_bool_field(object, "available", true)) return -1000;
    std::string slot = lower_copy(json_string_field(object, "slot"));
    std::string parameter = lower_copy(json_string_field(object, "parameter_name"));
    std::string semantic_type = lower_copy(json_string_field(object, "semantic_type"));
    std::string semantic_subtype = lower_copy(json_string_field(object, "semantic_subtype"));
    std::string descriptor = lower_copy(source_path + " " + slot + " " + parameter + " " + semantic_type + " " + semantic_subtype);
    int dimension_bonus = 0;
    int largest_dimension = std::max(json_int_field(object, "width", 0), json_int_field(object, "height", 0));
    if (largest_dimension >= 2048) dimension_bonus = 18;
    else if (largest_dimension >= 1024) dimension_bonus = 14;
    else if (largest_dimension >= 512) dimension_bonus = 8;

    if (role == "base") {
        int score = -1000;
        if (contains_text(descriptor, "normal") || looks_like_path_suffix(source_path, "_n")) score -= 240;
        if (contains_text(descriptor, "height") || contains_text(descriptor, "displacement") || looks_like_path_suffix(source_path, "_disp")) score -= 240;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "alpha")) score -= 220;
        if (looks_like_path_suffix(source_path, "_ma") || looks_like_path_suffix(source_path, "_mg") || looks_like_path_suffix(source_path, "_sp")) score -= 220;
        if (looks_like_path_suffix(source_path, "_o")) score = std::max(score, 118);
        if (contains_text(parameter, "basecolor") || contains_text(parameter, "diffuse") || contains_text(parameter, "albedo")) score = std::max(score, 108);
        if (contains_text(parameter, "overlaycolor") || contains_text(parameter, "colorlayer")) score = std::max(score, 92);
        if (semantic_type == "base" || semantic_type == "albedo" || semantic_type == "diffuse" || semantic_subtype == "base_color") score = std::max(score, 104);
        if (slot == "base") score = std::max(score, 96);
        if (contains_text(descriptor, "texturelayer") && score < 80) score = std::max(score, 70);
        if (score > -1000) score += dimension_bonus;
        return score;
    }
    if (role == "specular") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_sp")) score = std::max(score, 110);
        if (contains_text(parameter, "specular")) score = std::max(score, 100);
        if (semantic_subtype == "specular" || semantic_type == "specular") score = std::max(score, 96);
        if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score = std::max(score, 76);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "roughness") {
        int score = -1000;
        if (contains_text(parameter, "roughness") || semantic_subtype == "roughness" || semantic_type == "roughness") score = std::max(score, 100);
        if (contains_text(descriptor, "gloss") || contains_text(descriptor, "smoothness")) score -= 220;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "metalness") {
        int score = -1000;
        if (contains_text(parameter, "metallic") || contains_text(parameter, "metalness")) score = std::max(score, 100);
        if (semantic_subtype == "metallic" || semantic_subtype == "metalness" || semantic_type == "metallic") score = std::max(score, 96);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "occlusion") {
        int score = -1000;
        if (contains_text(parameter, "occlusion") || semantic_subtype == "ao" || semantic_subtype == "ambient_occlusion") score = std::max(score, 96);
        if (looks_like_path_suffix(source_path, "_ao")) score = std::max(score, 86);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "material") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_ma")) score = std::max(score, 112);
        if (semantic_subtype == "material_mask" || semantic_subtype == "material_response" || semantic_subtype == "packed_mask") score = std::max(score, 100);
        if (contains_text(parameter, "materialtexture") || contains_text(parameter, "materialmask")) score = std::max(score, 92);
        if (looks_like_path_suffix(source_path, "_m")) score = std::max(score, 72);
        if (looks_like_path_suffix(source_path, "_mg") || contains_text(parameter, "detailmask") || contains_text(parameter, "colorblendingmask")) score = std::max(score, 28);
        if (contains_text(descriptor, "specular") || looks_like_path_suffix(source_path, "_sp")) score -= 120;
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        return score;
    }
    if (role == "detail") {
        int score = -1000;
        if (looks_like_path_suffix(source_path, "_mg")) score = std::max(score, 108);
        if (contains_text(parameter, "detailmask")) score = std::max(score, 104);
        if (contains_text(parameter, "colorblendingmask")) score = std::max(score, 96);
        if (semantic_subtype == "detail_mask" || semantic_type == "detail_mask") score = std::max(score, 96);
        if (contains_text(descriptor, "opacity") || contains_text(descriptor, "normal") || contains_text(descriptor, "height")) score -= 200;
        if (score > -1000) score += dimension_bonus / 2;
        return score;
    }
    return -1000;
}

static std::wstring best_material_dds_for_role(const std::string& object, const std::string& role) {
    int best_score = -1000;
    std::string best_path;
    for (const std::string& candidate : objects_with_key(object, "source_path")) {
        int score = material_dds_candidate_score(candidate, role);
        if (score > best_score) {
            std::string source_path = json_string_field(candidate, "source_path");
            if (!source_path.empty()) {
                best_score = score;
                best_path = source_path;
            }
        }
    }
    int minimum_score = 40;
    if (role == "base") minimum_score = 58;
    else if (role == "detail") minimum_score = 32;
    if (best_score < minimum_score || best_path.empty()) return L"";
    return utf8_to_wide(best_path);
}

static float material_layer_channel_index(const std::string& channel) {
    std::string value = lower_copy(channel);
    if (value == "g") return 1.0f;
    if (value == "b") return 2.0f;
    if (value == "a") return 3.0f;
    return 0.0f;
}

static void parse_material_layer_object(PreviewMaterialLayer& layer, const std::string& object) {
    layer.role = json_string_field(object, "layer_role");
    layer.evidence_grade = json_string_field(object, "evidence_grade");
    layer.channel_index = material_layer_channel_index(json_string_field(object, "mask_channel", "r"));
    layer.weight = std::clamp(json_float_field(object, "weight", 0.0f), 0.0f, 1.0f);
    layer.diffuse_dds = utf8_to_wide(json_string_field(object, "diffuse_source"));
    layer.mask_dds = utf8_to_wide(json_string_field(object, "mask_source"));
    layer.material_dds = utf8_to_wide(json_string_field(object, "material_source"));
    layer.normal_dds = utf8_to_wide(json_string_field(object, "normal_source"));
    layer.height_dds = utf8_to_wide(json_string_field(object, "height_source"));
    layer.roughness_hint = std::clamp(json_float_field(object, "roughness_hint", 0.0f), 0.0f, 1.0f);
    layer.metalness_hint = std::clamp(json_float_field(object, "metalness_hint", 0.0f), 0.0f, 1.0f);
    layer.specular_hint = std::clamp(json_float_field(object, "specular_hint", 0.0f), 0.0f, 1.0f);
    layer.height_scale_hint = std::clamp(json_float_field(object, "height_scale_hint", 0.0f), 0.0f, 1.0f);
    const std::vector<float> tint = json_float_array_field(object, "tint");
    for (size_t index = 0; index < std::min<size_t>(4, tint.size()); ++index) {
        layer.tint[index] = std::clamp(tint[index], 0.0f, 2.0f);
    }
}

static void append_batch_material_layer(PreviewBatch& batch, const PreviewMaterialLayer& layer) {
    if (batch.material_layer_count >= kMaxMaterialLayers) return;
    if (layer.diffuse_dds.empty()) return;
    const std::string role = lower_copy(layer.role);
    if (role.empty() || role == "base") return;
    batch.material_layers[static_cast<size_t>(batch.material_layer_count)] = layer;
    ++batch.material_layer_count;
}

static void parse_material_layers(PreviewBatch& batch, const std::string& object) {
    for (const std::string& layer_object : json_object_array_field(object, "material_layers")) {
        PreviewMaterialLayer layer;
        parse_material_layer_object(layer, layer_object);
        append_batch_material_layer(batch, layer);
    }
}

static void parse_primary_material_layer(PreviewBatch& batch, const std::string& object) {
    const std::string layer = json_object_field(object, "primary_material_layer");
    if (layer.empty() || !json_bool_field(layer, "active", false)) return;
    batch.layer_role = json_string_field(layer, "layer_role");
    batch.layer_evidence_grade = json_string_field(layer, "evidence_grade");
    batch.layer_channel_index = material_layer_channel_index(json_string_field(layer, "mask_channel", "r"));
    batch.layer_weight = std::clamp(json_float_field(layer, "weight", 0.0f), 0.0f, 1.0f);
    batch.layer_diffuse_dds = utf8_to_wide(json_string_field(layer, "diffuse_source"));
    batch.layer_mask_dds = utf8_to_wide(json_string_field(layer, "mask_source"));
    batch.layer_material_dds = utf8_to_wide(json_string_field(layer, "material_source"));
    batch.layer_normal_dds = utf8_to_wide(json_string_field(layer, "normal_source"));
    batch.layer_height_dds = utf8_to_wide(json_string_field(layer, "height_source"));
    batch.layer_roughness_hint = std::clamp(json_float_field(layer, "roughness_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_metalness_hint = std::clamp(json_float_field(layer, "metalness_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_specular_hint = std::clamp(json_float_field(layer, "specular_hint", 0.0f), 0.0f, 1.0f);
    batch.layer_height_scale_hint = std::clamp(json_float_field(layer, "height_scale_hint", 0.0f), 0.0f, 1.0f);
    const std::vector<float> tint = json_float_array_field(layer, "tint");
    for (size_t index = 0; index < std::min<size_t>(4, tint.size()); ++index) {
        batch.layer_tint[index] = std::clamp(tint[index], 0.0f, 2.0f);
    }
    if (batch.material_layer_count == 0) {
        PreviewMaterialLayer compat_layer;
        compat_layer.role = batch.layer_role;
        compat_layer.evidence_grade = batch.layer_evidence_grade;
        compat_layer.channel_index = batch.layer_channel_index;
        compat_layer.weight = batch.layer_weight;
        compat_layer.diffuse_dds = batch.layer_diffuse_dds;
        compat_layer.mask_dds = batch.layer_mask_dds;
        compat_layer.material_dds = batch.layer_material_dds;
        compat_layer.normal_dds = batch.layer_normal_dds;
        compat_layer.height_dds = batch.layer_height_dds;
        compat_layer.roughness_hint = batch.layer_roughness_hint;
        compat_layer.metalness_hint = batch.layer_metalness_hint;
        compat_layer.specular_hint = batch.layer_specular_hint;
        compat_layer.height_scale_hint = batch.layer_height_scale_hint;
        for (size_t i = 0; i < 4; ++i) compat_layer.tint[i] = batch.layer_tint[i];
        append_batch_material_layer(batch, compat_layer);
    }
}

static void increment_slot(SlotCounts& counts, const std::string& slot) {
    if (slot == "base") ++counts.base;
    else if (slot == "normal") ++counts.normal;
    else if (slot == "material") ++counts.material;
    else if (slot == "height") ++counts.height;
    else if (slot == "occlusion") ++counts.occlusion;
    else if (slot == "roughness") ++counts.roughness;
    else if (slot == "metalness") ++counts.metalness;
    else if (slot == "specular") ++counts.specular;
    else if (slot == "detail" || slot == "layer_base") ++counts.detail;
    else if (slot == "emissive") ++counts.emissive;
}

static std::string slot_counts_json(const SlotCounts& counts) {
    std::ostringstream out;
    out << "{"
        << "\"base\":" << counts.base
        << ",\"normal\":" << counts.normal
        << ",\"material\":" << counts.material
        << ",\"height\":" << counts.height
        << ",\"occlusion\":" << counts.occlusion
        << ",\"roughness\":" << counts.roughness
        << ",\"metalness\":" << counts.metalness
        << ",\"specular\":" << counts.specular
        << ",\"detail\":" << counts.detail
        << ",\"emissive\":" << counts.emissive
        << "}";
    return out.str();
}

static std::string string_int_map_json(const std::map<std::string, int>& values) {
    std::ostringstream out;
    out << "{";
    size_t index = 0;
    for (const auto& [key, value] : values) {
        if (index++) out << ",";
        out << "\"" << json_escape(key) << "\":" << value;
    }
    out << "}";
    return out.str();
}

static std::string dxgi_format_name(DXGI_FORMAT format) {
    switch (format) {
    case DXGI_FORMAT_BC1_UNORM: return "DXGI_FORMAT_BC1_UNORM";
    case DXGI_FORMAT_BC1_UNORM_SRGB: return "DXGI_FORMAT_BC1_UNORM_SRGB";
    case DXGI_FORMAT_BC2_UNORM: return "DXGI_FORMAT_BC2_UNORM";
    case DXGI_FORMAT_BC2_UNORM_SRGB: return "DXGI_FORMAT_BC2_UNORM_SRGB";
    case DXGI_FORMAT_BC3_UNORM: return "DXGI_FORMAT_BC3_UNORM";
    case DXGI_FORMAT_BC3_UNORM_SRGB: return "DXGI_FORMAT_BC3_UNORM_SRGB";
    case DXGI_FORMAT_BC4_UNORM: return "DXGI_FORMAT_BC4_UNORM";
    case DXGI_FORMAT_BC4_SNORM: return "DXGI_FORMAT_BC4_SNORM";
    case DXGI_FORMAT_BC5_UNORM: return "DXGI_FORMAT_BC5_UNORM";
    case DXGI_FORMAT_BC5_SNORM: return "DXGI_FORMAT_BC5_SNORM";
    case DXGI_FORMAT_BC6H_UF16: return "DXGI_FORMAT_BC6H_UF16";
    case DXGI_FORMAT_BC6H_SF16: return "DXGI_FORMAT_BC6H_SF16";
    case DXGI_FORMAT_BC7_UNORM: return "DXGI_FORMAT_BC7_UNORM";
    case DXGI_FORMAT_BC7_UNORM_SRGB: return "DXGI_FORMAT_BC7_UNORM_SRGB";
    case DXGI_FORMAT_R8G8B8A8_UNORM: return "DXGI_FORMAT_R8G8B8A8_UNORM";
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: return "DXGI_FORMAT_R8G8B8A8_UNORM_SRGB";
    default: return "DXGI_FORMAT_" + std::to_string(static_cast<unsigned int>(format));
    }
}

static void parse_float3_array_field(const std::string& object, const std::string& field_name, float out_color[3]) {
    std::regex pattern("\"" + field_name + "\"\\s*:\\s*\\[([^\\]]*)\\]");
    std::smatch match;
    if (!std::regex_search(object, match, pattern)) return;
    std::string values = match[1].str();
    std::regex number_pattern("-?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    auto begin = std::sregex_iterator(values.begin(), values.end(), number_pattern);
    auto end = std::sregex_iterator();
    int index = 0;
    for (auto it = begin; it != end && index < 3; ++it, ++index) {
        try {
            out_color[index] = std::clamp(std::stof(it->str()), 0.0f, 1.5f);
        } catch (...) {
        }
    }
}

static void parse_base_color(const std::string& object, float out_color[3]) {
    parse_float3_array_field(object, "base_color", out_color);
}

static float material_family_code(const std::string& shader_family) {
    const std::string family = lower_copy(shader_family);
    if (family == "skin") return 1.0f;
    if (family == "hair") return 2.0f;
    if (family == "cloth" || family == "cloth_v2") return 3.0f;
    if (family == "standard" || family == "standard_v2") return 4.0f;
    if (family == "static_standard" || family == "static_multitextured") return 5.0f;
    if (family == "emissive" || family == "emissive_v2") return 6.0f;
    return 0.0f;
}

static float material_category_code(const std::string& category) {
    const std::string value = lower_copy(category);
    if (value == "metal") return 1.0f;
    if (value == "leather") return 2.0f;
    if (value == "wood") return 3.0f;
    if (value == "cloth") return 4.0f;
    if (value == "skin") return 5.0f;
    if (value == "hair") return 6.0f;
    if (value == "glass") return 7.0f;
    if (value == "gem") return 8.0f;
    if (value == "stone") return 9.0f;
    if (value == "eye") return 10.0f;
    if (value == "tooth") return 11.0f;
    return 0.0f;
}

static float boosted_preview_layer_weight(const PreviewMaterialLayer& layer, int layer_index) {
    (void)layer_index;
    return std::clamp(layer.weight, 0.0f, 1.0f);
}

static std::vector<PreviewBatch> parse_manifest_batches(const fs::path& package_dir, const std::string& manifest, RendererStats& stats) {
    std::vector<PreviewBatch> batches;
    for (const std::string& object : objects_with_key(manifest, "vertex_file")) {
        PreviewBatch batch;
        batch.index = json_int_field(object, "index", static_cast<int>(batches.size()));
        batch.vertex_count = json_int_field(object, "vertex_count", 0);
        batch.flip_v = json_bool_field(object, "texture_flip_vertical", false);
        batch.alpha_cutout = lower_copy(json_string_field(object, "alpha_mode")).find("cutout") != std::string::npos;
        batch.two_sided = json_bool_field(object, "two_sided", json_bool_field(object, "double_sided", false));
        batch.alpha_threshold = std::clamp(json_float_field(object, "alpha_threshold", batch.alpha_cutout ? 0.12f : 0.0f), 0.0f, 0.95f);
        const std::string normal_y_policy = lower_copy(json_string_field(object, "normal_y_policy"));
        batch.invert_normal_y = normal_y_policy.empty()
            || normal_y_policy.find("invert") != std::string::npos
            || normal_y_policy.find("legacy") != std::string::npos;
        parse_base_color(object, batch.base_color);
        batch.vertex_file = absolute_from_manifest_path(package_dir, json_string_field(object, "vertex_file"));
        batch.vertex_offset = json_uint64_field(object, "vertex_offset", 0);
        batch.vertex_size = json_uint64_field(object, "vertex_size", 0);
        batch.base_dds = dds_slot_source(object, "base");
        batch.normal_dds = dds_slot_source(object, "normal");
        batch.material_dds = dds_slot_source(object, "material");
        if (batch.material_dds.empty()) batch.material_dds = best_material_dds_for_role(object, "material");
        batch.occlusion_dds = best_material_dds_for_role(object, "occlusion");
        batch.roughness_dds = best_material_dds_for_role(object, "roughness");
        batch.metalness_dds = best_material_dds_for_role(object, "metalness");
        batch.specular_dds = best_material_dds_for_role(object, "specular");
        batch.detail_dds = best_material_dds_for_role(object, "detail");
        batch.height_dds = dds_slot_source(object, "height");
        batch.emissive_dds = dds_slot_source(object, "emissive");
        batch.base_png = texture_slot_relative(package_dir, object, "base");
        batch.normal_png = texture_slot_relative(package_dir, object, "normal");
        batch.occlusion_png = texture_slot_relative(package_dir, object, "occlusion");
        batch.roughness_png = texture_slot_relative(package_dir, object, "roughness");
        batch.metalness_png = texture_slot_relative(package_dir, object, "metalness");
        batch.specular_png = texture_slot_relative(package_dir, object, "specular");
        batch.height_png = texture_slot_relative(package_dir, object, "height");
        batch.emissive_png = texture_slot_relative(package_dir, object, "emissive");
        if (json_bool_field(object, "prefer_generated_base_texture", false) && !batch.base_png.empty()) {
            batch.base_dds.clear();
        }
        batch.normal_strength = std::clamp(json_float_field(object, "normal_strength", 1.0f), 0.0f, 2.0f);
        batch.height_amount = std::clamp(json_float_field(object, "height_amount", 0.0f), 0.0f, 0.16f);
        batch.roughness_hint = std::clamp(json_float_field(object, "roughness", 0.0f), 0.0f, 1.0f);
        batch.metalness_hint = std::clamp(json_float_field(object, "metalness", 0.0f), 0.0f, 1.0f);
        batch.specular_hint = std::clamp(json_float_field(object, "specular", 0.0f), 0.0f, 1.0f);
        batch.height_scale_hint = std::clamp(json_float_field(object, "height_scale", 0.0f), 0.0f, 1.0f);
        batch.emissive_intensity = std::clamp(json_float_field(object, "emissive_intensity", 0.0f), 0.0f, 32.0f);
        parse_float3_array_field(object, "emissive_color", batch.emissive_color);
        batch.highlight_strength = std::clamp(json_float_field(object, "highlight_strength", 0.0f), 0.0f, 1.0f);
        batch.base_tint_strength = std::clamp(json_float_field(object, "base_tint_strength", 0.0f), 0.0f, 1.0f);
        batch.texture_brightness = std::clamp(json_float_field(object, "texture_brightness", 1.0f), 0.1f, 3.0f);
        batch.texture_contrast = std::clamp(json_float_field(object, "texture_contrast", 1.0f), 0.25f, 2.5f);
        batch.texture_saturation = std::clamp(json_float_field(object, "texture_saturation", 1.0f), 0.0f, 4.0f);
        batch.texture_gamma = std::clamp(json_float_field(object, "texture_gamma", 1.0f), 0.25f, 4.0f);
        parse_float3_array_field(object, "texture_tint", batch.texture_tint);
        const std::vector<float> texture_uv_scale = json_float_array_field(object, "texture_uv_scale");
        if (!texture_uv_scale.empty()) {
            batch.texture_uv_scale[0] = std::clamp(texture_uv_scale[0], 0.05f, 64.0f);
            batch.texture_uv_scale[1] = texture_uv_scale.size() > 1
                ? std::clamp(texture_uv_scale[1], 0.05f, 64.0f)
                : batch.texture_uv_scale[0];
        }
        batch.material_shader_family = lower_copy(json_string_field(object, "material_shader_family"));
        if (batch.material_shader_family.empty()) {
            batch.material_shader_family = lower_copy(json_string_field(object, "shader_rule"));
        }
        if (batch.material_shader_family.empty()) {
            batch.material_shader_family = lower_copy(json_string_field(object, "shader_family", "generic"));
        }
        batch.material_family_code = material_family_code(batch.material_shader_family);
        batch.material_category_code = material_category_code(json_string_field(object, "material_category", "generic"));
        batch.material_category_confidence = std::clamp(json_float_field(object, "material_category_confidence", 0.35f), 0.0f, 1.0f);
        batch.material_response_promoted = json_bool_field(object, "material_response_promoted", false);
        batch.low_authority_base_overlay = json_bool_field(object, "base_low_authority_overlay", false);
        parse_material_layers(batch, object);
        parse_primary_material_layer(batch, object);
        std::string editor_identity = json_object_field(object, "editor_identity");
        batch.source_submesh_index = json_int_field(editor_identity, "source_submesh_index", -1);
        batch.source_local_submesh_index = json_int_field(editor_identity, "source_local_submesh_index", batch.source_submesh_index);
        batch.source_component_index = json_int_field(editor_identity, "source_component_index", 0);
        batch.source_vertex_count = json_int_field(editor_identity, "source_vertex_count", 0);
        batch.source_face_count = json_int_field(editor_identity, "source_face_count", 0);
        batch.identity_file = absolute_from_manifest_path(package_dir, json_string_field(editor_identity, "identity_file"));
        batch.identity_offset = json_uint64_field(editor_identity, "identity_offset", 0);
        batch.identity_size = json_uint64_field(editor_identity, "identity_size", 0);
        batch.identity_stride_bytes = json_uint64_field(editor_identity, "identity_stride_bytes", 0);
        batch.source_model_path = json_string_field(editor_identity, "source_model_path");
        batch.source_component_label = json_string_field(editor_identity, "source_component_label");
        batch.part_label = json_string_field(editor_identity, "part_label");
        batch.prefab_component = json_bool_field(editor_identity, "prefab_component", false);
        batch.editor_role = lower_copy(json_string_field(editor_identity, "role"));
        batch.editor_editable = json_bool_field(editor_identity, "editable", batch.source_submesh_index >= 0);
        if (batch.editor_role.find("original") != std::string::npos
            || batch.editor_role.find("reference") != std::string::npos) {
            batch.editor_editable = false;
        }
        batch.cloth.available = json_bool_field(object, "cloth_enabled", false);
        if (batch.cloth.available) {
            batch.cloth.kind = lower_copy(json_string_field(object, "cloth_kind", "cloth"));
            batch.cloth.material_name = json_string_field(object, "cloth_material_name");
            batch.cloth.particle_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_particle_file"));
            batch.cloth.pin_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_pin_file"));
            batch.cloth.constraint_file = absolute_from_manifest_path(package_dir, json_string_field(object, "cloth_constraint_file"));
            batch.cloth.particle_count = std::max(0, json_int_field(object, "cloth_particle_count", 0));
            batch.cloth.constraint_count = std::max(0, json_int_field(object, "cloth_constraint_count", 0));
            batch.cloth.gravity = std::clamp(json_float_field(object, "cloth_gravity", -10.0f), -50.0f, 50.0f);
            batch.cloth.damping = std::clamp(json_float_field(object, "cloth_damping", 0.65f), 0.0f, 4.0f);
            batch.cloth.air_resistance = std::clamp(json_float_field(object, "cloth_air_resistance", 1.0f), 0.0f, 8.0f);
            batch.cloth.wind_response = std::clamp(json_float_field(object, "cloth_wind_response", 0.4f), 0.0f, 4.0f);
            batch.cloth.solver_iterations = std::clamp(json_int_field(object, "cloth_solver_iterations", 30), 1, 64);
            batch.cloth.collision_enabled = json_bool_field(object, "cloth_collision_enabled", true);
            ++stats.cloth_batch_count;
            stats.cloth_particle_count += batch.cloth.particle_count;
            stats.cloth_constraint_count += batch.cloth.constraint_count;
        }
        if (!batch.base_dds.empty()) increment_slot(stats.dds_candidates, "base");
        if (!batch.normal_dds.empty()) increment_slot(stats.dds_candidates, "normal");
        if (!batch.material_dds.empty()) increment_slot(stats.dds_candidates, "material");
        if (!batch.occlusion_dds.empty()) increment_slot(stats.dds_candidates, "occlusion");
        if (!batch.roughness_dds.empty()) increment_slot(stats.dds_candidates, "roughness");
        if (!batch.metalness_dds.empty()) increment_slot(stats.dds_candidates, "metalness");
        if (!batch.specular_dds.empty()) increment_slot(stats.dds_candidates, "specular");
        if (!batch.detail_dds.empty()) increment_slot(stats.dds_candidates, "detail");
        if (!batch.height_dds.empty()) increment_slot(stats.dds_candidates, "height");
        if (!batch.emissive_dds.empty()) increment_slot(stats.dds_candidates, "emissive");
        for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
            const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
            if (!layer.diffuse_dds.empty()) increment_slot(stats.dds_candidates, "detail");
            if (!layer.mask_dds.empty()) increment_slot(stats.dds_candidates, "detail");
            if (!layer.material_dds.empty()) increment_slot(stats.dds_candidates, "material");
            if (!layer.normal_dds.empty()) increment_slot(stats.dds_candidates, "normal");
            if (!layer.height_dds.empty()) increment_slot(stats.dds_candidates, "height");
            ++stats.material_layer_count;
            ++stats.material_layer_roles[layer.role.empty() ? "layer" : lower_copy(layer.role)];
        }
        if (batch.material_layer_count > 0) {
            ++stats.material_layer_active_batches;
        }
        if (json_bool_field(object, "material_combiner_active", false)) {
            ++stats.material_combiner_active_batches;
        }
        for (const std::string& output : json_string_array_field(object, "material_combiner_outputs")) {
            ++stats.material_combiner_outputs[output];
        }
        for (const std::string& mode : json_string_array_field(object, "material_combiner_decode_modes")) {
            ++stats.material_combiner_decode_modes[mode];
        }
        if (batch.vertex_count > 0 && !batch.vertex_file.empty()) {
            batches.push_back(batch);
        }
    }
    stats.batch_count = static_cast<int>(batches.size());
    stats.vertex_count = json_int_field(manifest, "vertex_count", 0);
    stats.cloth_collider_count = std::max(0, json_int_field(manifest, "cloth_collider_count", 0));
    stats.pbd_hint_count = std::max(0, json_int_field(manifest, "pbd_hint_count", 0));
    stats.pbd_soft_hint_count = std::max(0, json_int_field(manifest, "pbd_soft_hint_count", 0));
    stats.pbd_cloth_hint_count = std::max(0, json_int_field(manifest, "pbd_cloth_hint_count", 0));
    stats.material_contract_schema = std::max(0, json_int_field(manifest, "material_contract_schema", 0));
    stats.material_channel_contract_schema = std::max(0, json_int_field(manifest, "material_channel_contract_schema", 0));
    stats.texture_quality_schema = std::max(0, json_int_field(manifest, "texture_quality_schema", 0));
    stats.cloth_runtime_schema = std::max(0, json_int_field(manifest, "cloth_runtime_schema", 0));
    stats.render_diagnostic_mode = json_string_field(manifest, "d3d11_view_mode");
    if (stats.render_diagnostic_mode.empty()) {
        stats.render_diagnostic_mode = json_string_field(manifest, "render_diagnostic_mode");
    }
    stats.lighting_preset = json_string_field(manifest, "lighting_preset");
    const std::string physics_overlays = json_object_field(manifest, "physics_overlays");
    if (!physics_overlays.empty()) {
        stats.physics_overlay_enabled = json_bool_field(physics_overlays, "enabled", false);
        stats.physics_overlay_cloth = json_bool_field(physics_overlays, "cloth", false);
        stats.physics_shape_count = std::max(0, json_int_field(physics_overlays, "physics_shape_count", 0));
        stats.physics_anchor_count = std::max(0, json_int_field(physics_overlays, "anchor_count", 0));
        stats.physics_constraint_count = std::max(0, json_int_field(physics_overlays, "constraint_count", 0));
    }
    const std::string cloth_runtime_debug = json_object_field(manifest, "cloth_runtime_debug");
    if (!cloth_runtime_debug.empty()) {
        stats.cloth_runtime_debug_enabled = json_bool_field(cloth_runtime_debug, "enabled", false);
    }
    const std::string skeleton_overlay = json_object_field(manifest, "skeleton_overlay");
    if (!skeleton_overlay.empty()) {
        stats.skeleton_bone_count = std::max(0, json_int_field(skeleton_overlay, "bone_count", 0));
        stats.skeleton_overlay_enabled = json_bool_field(skeleton_overlay, "enabled", false) && stats.skeleton_bone_count > 0;
        stats.skeleton_pose_enabled = json_bool_field(skeleton_overlay, "pose_enabled", false);
        stats.skeleton_selected_bone_index = json_int_field(skeleton_overlay, "selected_bone_index", -1);
        stats.skeleton_posed_bone_count = std::max(0, json_int_field(skeleton_overlay, "posed_bone_count", 0));
    }
    stats.editable_value_group_count = static_cast<int>(json_object_array_field(manifest, "editable_value_groups").size());
    return batches;
}

static bool json_vec3_field(const std::string& object, const std::string& name, DirectX::XMFLOAT3& output) {
    const std::vector<float> values = json_float_array_field(object, name);
    if (values.size() < 3) return false;
    if (!std::isfinite(values[0]) || !std::isfinite(values[1]) || !std::isfinite(values[2])) return false;
    output = DirectX::XMFLOAT3(values[0], values[1], values[2]);
    return true;
}

static SkeletonOverlayState parse_skeleton_overlay_state(const std::string& manifest, RendererStats& stats) {
    SkeletonOverlayState state;
    const std::string skeleton_overlay = json_object_field(manifest, "skeleton_overlay");
    if (skeleton_overlay.empty()) return state;
    stats.skeleton_bone_count = std::max(0, json_int_field(skeleton_overlay, "bone_count", 0));
    stats.skeleton_overlay_enabled = json_bool_field(skeleton_overlay, "enabled", false) && stats.skeleton_bone_count > 0;
    stats.skeleton_pose_enabled = json_bool_field(skeleton_overlay, "pose_enabled", false);
    stats.skeleton_selected_bone_index = json_int_field(skeleton_overlay, "selected_bone_index", -1);
    stats.skeleton_posed_bone_count = std::max(0, json_int_field(skeleton_overlay, "posed_bone_count", 0));
    state.enabled = stats.skeleton_overlay_enabled;
    state.pose_enabled = stats.skeleton_pose_enabled;
    state.selected_bone_index = stats.skeleton_selected_bone_index;
    std::map<int, DirectX::XMFLOAT3> positions_by_index;
    for (const std::string& object : json_object_array_field(skeleton_overlay, "bones")) {
        SkeletonOverlayBoneState bone;
        bone.index = json_int_field(object, "index", -1);
        bone.parent_index = json_int_field(object, "parent_index", -1);
        bone.has_position = json_vec3_field(object, "position", bone.position);
        bone.has_parent_position = json_vec3_field(object, "parent_position", bone.parent_position);
        if (bone.index >= 0 && bone.has_position) {
            positions_by_index[bone.index] = bone.position;
        }
        if (bone.index >= 0) {
            state.bones.push_back(bone);
        }
        if (state.bones.size() >= 4096u) break;
    }
    for (SkeletonOverlayBoneState& bone : state.bones) {
        if (!bone.has_parent_position && bone.parent_index >= 0) {
            auto parent = positions_by_index.find(bone.parent_index);
            if (parent != positions_by_index.end()) {
                bone.parent_position = parent->second;
                bone.has_parent_position = true;
            }
        }
    }
    if (state.bones.empty()) {
        state.enabled = false;
        stats.skeleton_overlay_enabled = false;
    }
    return state;
}

static ViewSettings parse_view_settings(const std::string& manifest) {
    ViewSettings settings;
    settings.orbit_sensitivity = std::clamp(json_float_field(manifest, "orbit_sensitivity", settings.orbit_sensitivity), 0.001f, 8.0f);
    settings.pan_sensitivity = std::clamp(json_float_field(manifest, "pan_sensitivity", settings.pan_sensitivity), 0.001f, 8.0f);
    settings.invert_orbit_x = json_bool_field(manifest, "invert_orbit_x", settings.invert_orbit_x);
    settings.invert_orbit_y = json_bool_field(manifest, "invert_orbit_y", settings.invert_orbit_y);
    settings.invert_pan_x = json_bool_field(manifest, "invert_pan_x", settings.invert_pan_x);
    settings.invert_pan_y = json_bool_field(manifest, "invert_pan_y", settings.invert_pan_y);
    return settings;
}

static void apply_render_tuning_preset(RenderTuning& tuning, const std::string& normalized_view_mode, const std::string& normalized_lighting_preset) {
    if (normalized_view_mode == "shiny_metal_inspection" || normalized_lighting_preset == "shiny_metal_inspection") {
        tuning.diagnostic_mode = 0;
        tuning.ao_strength = std::max(tuning.ao_strength, 0.45f);
        tuning.roughness_bias = std::min(tuning.roughness_bias, -0.04f);
        tuning.environment_strength = std::max(tuning.environment_strength, 0.62f);
        tuning.ambient_strength = std::max(tuning.ambient_strength, 0.84f);
        tuning.diffuse_wrap_bias = std::min(tuning.diffuse_wrap_bias, 0.58f);
        tuning.diffuse_light_scale = std::max(tuning.diffuse_light_scale, 0.62f);
        tuning.specular_base = std::max(tuning.specular_base, 0.055f);
        tuning.specular_max = std::max(tuning.specular_max, 0.52f);
        tuning.tone_exposure = std::max(tuning.tone_exposure, 1.00f);
        tuning.tone_contrast = std::max(tuning.tone_contrast, 1.08f);
        tuning.tone_gamma = std::min(tuning.tone_gamma, 1.00f);
    } else if (normalized_view_mode == "game_outdoor" || normalized_view_mode == "cd_outdoor" || normalized_view_mode == "outdoor_game") {
        tuning.diagnostic_mode = 0;
        tuning.light_elevation_degrees = std::max(tuning.light_elevation_degrees, 42.0f);
        tuning.ao_strength = std::min(tuning.ao_strength, 0.55f);
        tuning.roughness_bias = std::min(tuning.roughness_bias, 0.04f);
        tuning.environment_strength = std::max(tuning.environment_strength, 0.70f);
        tuning.emissive_gain = std::max(tuning.emissive_gain, 1.80f);
        tuning.ambient_strength = std::max(tuning.ambient_strength, 0.78f);
        tuning.diffuse_wrap_bias = std::max(tuning.diffuse_wrap_bias, 0.70f);
        tuning.diffuse_light_scale = std::max(tuning.diffuse_light_scale, 1.05f);
        tuning.specular_max = std::max(tuning.specular_max, 0.22f);
    }
}

static RenderTuning parse_render_tuning(const std::string& manifest) {
    RenderTuning tuning;
    const std::string d3d11_view_mode = json_string_field(manifest, "d3d11_view_mode");
    const std::string normalized_view_mode = lower_copy(d3d11_view_mode);
    const std::string normalized_lighting_preset = lower_copy(json_string_field(manifest, "lighting_preset"));
    const bool has_explicit_render_tuning =
        manifest.find("\"d3d11_mip_lod_bias\"") != std::string::npos ||
        manifest.find("\"ambient_strength\"") != std::string::npos ||
        manifest.find("\"diffuse_wrap_bias\"") != std::string::npos ||
        manifest.find("\"specular_base\"") != std::string::npos;
    tuning.diagnostic_mode = diagnostic_mode_code(d3d11_view_mode.empty() ? json_string_field(manifest, "render_diagnostic_mode") : d3d11_view_mode);
    tuning.max_anisotropy = std::clamp(json_int_field(manifest, "max_anisotropy", tuning.max_anisotropy), 1, 16);
    tuning.mip_lod_bias = std::clamp(json_float_field(manifest, "d3d11_mip_lod_bias", tuning.mip_lod_bias), -2.0f, 1.0f);
    tuning.cull_back_faces = json_bool_field(manifest, "d3d11_cull_back_faces", tuning.cull_back_faces);
    tuning.light_azimuth_degrees = std::clamp(json_float_field(manifest, "d3d11_light_azimuth_degrees", tuning.light_azimuth_degrees), -180.0f, 180.0f);
    tuning.light_elevation_degrees = std::clamp(json_float_field(manifest, "d3d11_light_elevation_degrees", tuning.light_elevation_degrees), -80.0f, 80.0f);
    const std::string normal_y_mode = lower_copy(json_string_field(manifest, "d3d11_normal_y_mode", "asset"));
    tuning.normal_y_mode = normal_y_mode == "force_flip" ? 1 : (normal_y_mode == "force_no_flip" ? 2 : 0);
    tuning.ao_strength = std::clamp(json_float_field(manifest, "d3d11_ao_strength", tuning.ao_strength), 0.0f, 2.0f);
    tuning.roughness_bias = std::clamp(json_float_field(manifest, "d3d11_roughness_bias", tuning.roughness_bias), -0.5f, 0.5f);
    tuning.metalness_scale = std::clamp(json_float_field(manifest, "d3d11_metalness_scale", tuning.metalness_scale), 0.0f, 2.0f);
    tuning.environment_strength = std::clamp(json_float_field(manifest, "d3d11_environment_strength", tuning.environment_strength), 0.0f, 2.0f);
    tuning.emissive_gain = std::clamp(json_float_field(manifest, "d3d11_emissive_gain", tuning.emissive_gain), 0.0f, 4.0f);
    tuning.tone_exposure = std::clamp(json_float_field(manifest, "d3d11_tone_exposure", tuning.tone_exposure), 0.25f, 2.0f);
    tuning.tone_contrast = std::clamp(json_float_field(manifest, "d3d11_tone_contrast", tuning.tone_contrast), 0.50f, 1.75f);
    tuning.tone_gamma = std::clamp(json_float_field(manifest, "d3d11_tone_gamma", tuning.tone_gamma), 0.50f, 2.20f);
    tuning.texture_address_mode = lower_copy(json_string_field(manifest, "d3d11_texture_address_mode", tuning.texture_address_mode));
    if (tuning.texture_address_mode != "clamp") tuning.texture_address_mode = "wrap";
    tuning.ambient_strength = std::clamp(json_float_field(manifest, "ambient_strength", tuning.ambient_strength), 0.05f, 1.20f);
    tuning.diffuse_wrap_bias = std::clamp(json_float_field(manifest, "diffuse_wrap_bias", tuning.diffuse_wrap_bias), 0.0f, 1.0f);
    tuning.diffuse_light_scale = std::clamp(json_float_field(manifest, "diffuse_light_scale", tuning.diffuse_light_scale), 0.05f, 1.50f);
    tuning.specular_base = std::clamp(json_float_field(manifest, "specular_base", tuning.specular_base), 0.0f, 0.50f);
    tuning.specular_max = std::clamp(json_float_field(manifest, "specular_max", tuning.specular_max), tuning.specular_base, 1.00f);
    tuning.shininess_min = std::clamp(json_float_field(manifest, "shininess_min", tuning.shininess_min), 1.0f, 128.0f);
    tuning.shininess_max = std::clamp(json_float_field(manifest, "shininess_max", tuning.shininess_max), tuning.shininess_min, 256.0f);
    if (!has_explicit_render_tuning) {
        apply_render_tuning_preset(tuning, normalized_view_mode, normalized_lighting_preset);
    }
    return tuning;
}

static std::vector<ClothCollider> parse_cloth_colliders(const fs::path& package_dir, const std::string& manifest) {
    std::vector<ClothCollider> colliders;
    std::wstring path = absolute_from_manifest_path(package_dir, json_string_field(manifest, "cloth_collider_file"));
    if (path.empty() || !fs::is_regular_file(fs::path(path))) return colliders;
    std::vector<uint8_t> data = read_binary(path);
    constexpr size_t kRecordFloats = 11u;
    constexpr size_t kRecordBytes = kRecordFloats * sizeof(float);
    const size_t record_count = data.size() / kRecordBytes;
    colliders.reserve(record_count);
    for (size_t index = 0; index < record_count; ++index) {
        const float* values = reinterpret_cast<const float*>(data.data() + index * kRecordBytes);
        ClothCollider collider;
        collider.type = static_cast<int>(std::round(values[0]));
        if (collider.type == 1) {
            collider.a = DirectX::XMFLOAT3(values[1], values[2], values[3]);
            collider.radius = std::max(0.0f, values[4]);
        } else if (collider.type == 2) {
            collider.a = DirectX::XMFLOAT3(values[1], values[2], values[3]);
            collider.b = DirectX::XMFLOAT3(values[4], values[5], values[6]);
            collider.radius = std::max(0.0f, values[7]);
        } else if (collider.type == 3) {
            collider.a = DirectX::XMFLOAT3(
                std::min(values[1], values[4]),
                std::min(values[2], values[5]),
                std::min(values[3], values[6]));
            collider.b = DirectX::XMFLOAT3(
                std::max(values[1], values[4]),
                std::max(values[2], values[5]),
                std::max(values[3], values[6]));
        } else {
            continue;
        }
        colliders.push_back(collider);
    }
    return colliders;
}

static DirectX::XMFLOAT4 parse_hex_color(const std::string& hex, DirectX::XMFLOAT4 fallback) {
    if (hex.size() < 7 || hex[0] != '#') return fallback;
    try {
        int r = std::stoi(hex.substr(1, 2), nullptr, 16);
        int g = std::stoi(hex.substr(3, 2), nullptr, 16);
        int b = std::stoi(hex.substr(5, 2), nullptr, 16);
        return DirectX::XMFLOAT4(r / 255.0f, g / 255.0f, b / 255.0f, 1.0f);
    } catch (...) {
        return fallback;
    }
}

static std::string skipped_json(const std::vector<std::string>& skipped) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < skipped.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(skipped[i]) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string string_array_json(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) out << ",";
        out << "\"" << json_escape(values[i]) << "\"";
    }
    out << "]";
    return out.str();
}

static std::string hresult_hex(HRESULT hr) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex << static_cast<unsigned long>(static_cast<unsigned int>(hr));
    return out.str();
}

static std::string failed_texture_json(const std::string& item) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (parts.size() < 5) {
        const size_t pos = item.find('|', start);
        if (pos == std::string::npos) {
            parts.push_back(item.substr(start));
            break;
        }
        parts.push_back(item.substr(start, pos - start));
        start = pos + 1;
    }
    while (parts.size() < 5) parts.push_back("");
    std::ostringstream out;
    out << "{"
        << "\"slot\":\"" << json_escape(parts[0]) << "\","
        << "\"path\":\"" << json_escape(parts[1]) << "\","
        << "\"stage\":\"" << json_escape(parts[2]) << "\","
        << "\"hresult\":\"" << json_escape(parts[3]) << "\","
        << "\"message\":\"" << json_escape(parts[4]) << "\""
        << "}";
    return out.str();
}

static std::string failed_textures_json(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size() && i < 24; ++i) {
        if (i) out << ",";
        out << failed_texture_json(values[i]);
    }
    out << "]";
    return out.str();
}

static std::string float3_json(const DirectX::XMFLOAT3& value) {
    std::ostringstream out;
    out << "[" << value.x << "," << value.y << "," << value.z << "]";
    return out.str();
}

static std::string matrix4x4_json(const DirectX::XMFLOAT4X4& value) {
    std::ostringstream out;
    out << "["
        << value._11 << "," << value._12 << "," << value._13 << "," << value._14 << ","
        << value._21 << "," << value._22 << "," << value._23 << "," << value._24 << ","
        << value._31 << "," << value._32 << "," << value._33 << "," << value._34 << ","
        << value._41 << "," << value._42 << "," << value._43 << "," << value._44
        << "]";
    return out.str();
}

static std::string float3_delta_json(const DirectX::XMFLOAT3& value) {
    return float3_json(value);
}

static std::string loaded_payload_for_event(const RendererStats& stats, const std::string& event_name) {
    std::ostringstream loaded;
    loaded << "{"
           << "\"event\":\"" << json_escape(event_name.empty() ? "loaded" : event_name) << "\","
           << "\"backend\":\"D3D11\","
           << "\"batch_count\":" << stats.batch_count << ","
           << "\"vertex_count\":" << stats.vertex_count << ","
           << "\"textures\":" << slot_counts_json(stats.textures_loaded) << ","
           << "\"png_fallback\":" << stats.png_fallback << ","
           << "\"texture_cache_hits\":" << stats.texture_cache_hits << ","
           << "\"low_resolution_base_textures\":" << stats.low_resolution_base_textures << ","
           << "\"srgb_color_uploads\":" << stats.srgb_color_uploads << ","
           << "\"linear_data_uploads\":" << stats.linear_data_uploads << ","
           << "\"png_fallbacks\":" << slot_counts_json(stats.png_uploaded) << ","
           << "\"dds_direct_upload_candidates\":" << slot_counts_json(stats.dds_candidates) << ","
           << "\"dds_direct_uploads\":" << slot_counts_json(stats.dds_uploaded) << ","
           << "\"dds_upload_formats\":" << string_int_map_json(stats.dds_upload_formats) << ","
           << "\"material_combiner_active\":" << stats.material_combiner_active_batches << ","
           << "\"material_combiner_outputs\":" << string_int_map_json(stats.material_combiner_outputs) << ","
           << "\"material_combiner_decode_modes\":" << string_int_map_json(stats.material_combiner_decode_modes) << ","
           << "\"material_layer_active\":" << stats.material_layer_active_batches << ","
           << "\"material_layer_count\":" << stats.material_layer_count << ","
           << "\"material_layer_roles\":" << string_int_map_json(stats.material_layer_roles) << ","
           << "\"material_contract_schema\":" << stats.material_contract_schema << ","
           << "\"material_channel_contract_schema\":" << stats.material_channel_contract_schema << ","
           << "\"texture_quality_schema\":" << stats.texture_quality_schema << ","
           << "\"cloth_runtime_schema\":" << stats.cloth_runtime_schema << ","
           << "\"render_diagnostic_mode\":\"" << json_escape(stats.render_diagnostic_mode) << "\","
           << "\"lighting_preset\":\"" << json_escape(stats.lighting_preset) << "\","
           << "\"physics_overlay_enabled\":" << (stats.physics_overlay_enabled ? "true" : "false") << ","
           << "\"physics_overlay_cloth\":" << (stats.physics_overlay_cloth ? "true" : "false") << ","
           << "\"physics_shape_count\":" << stats.physics_shape_count << ","
           << "\"physics_anchor_count\":" << stats.physics_anchor_count << ","
           << "\"physics_constraint_count\":" << stats.physics_constraint_count << ","
           << "\"cloth_runtime_debug_enabled\":" << (stats.cloth_runtime_debug_enabled ? "true" : "false") << ","
           << "\"skeleton_overlay_enabled\":" << (stats.skeleton_overlay_enabled ? "true" : "false") << ","
           << "\"skeleton_bone_count\":" << stats.skeleton_bone_count << ","
           << "\"skeleton_pose_enabled\":" << (stats.skeleton_pose_enabled ? "true" : "false") << ","
           << "\"skeleton_selected_bone_index\":" << stats.skeleton_selected_bone_index << ","
           << "\"skeleton_posed_bone_count\":" << stats.skeleton_posed_bone_count << ","
           << "\"editable_value_group_count\":" << stats.editable_value_group_count << ","
           << "\"semantic_writes_enabled\":false,"
           << "\"cloth_batch_count\":" << stats.cloth_batch_count << ","
           << "\"cloth_particle_count\":" << stats.cloth_particle_count << ","
           << "\"cloth_constraint_count\":" << stats.cloth_constraint_count << ","
           << "\"cloth_collider_count\":" << stats.cloth_collider_count << ","
           << "\"pbd_hint_count\":" << stats.pbd_hint_count << ","
           << "\"pbd_soft_hint_count\":" << stats.pbd_soft_hint_count << ","
           << "\"pbd_cloth_hint_count\":" << stats.pbd_cloth_hint_count << ","
           << "\"cloth_simulation_steps\":" << stats.cloth_simulation_steps << ","
           << "\"manifest_read_ms\":" << stats.manifest_ms << ","
           << "\"texture_bind_ms\":" << stats.texture_ms << ","
           << "\"geometry_upload_ms\":" << stats.geometry_ms << ","
           << "\"native_manifest_ms\":" << stats.manifest_ms << ","
           << "\"native_geometry_ms\":" << stats.geometry_ms << ","
           << "\"native_texture_ms\":" << stats.texture_ms << ","
           << "\"first_frame_ms\":" << stats.first_frame_ms << ","
           << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
           << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
           << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
           << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
           << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
           << "\"texture_failures\":" << stats.texture_failures << ","
           << "\"failed_textures\":" << failed_textures_json(stats.failed_textures) << ","
           << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
           << "\"process_private_bytes\":" << stats.process_private_bytes << ","
           << "\"frame_count\":" << stats.frame_count << ","
           << "\"render_request_count\":" << stats.render_request_count << ","
           << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
           << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
           << "\"render_suppressed_reason\":\"" << json_escape(stats.render_suppressed_reason) << "\","
           << "\"parent_renderable\":" << (stats.parent_renderable ? "true" : "false") << ","
           << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
           << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\","
           << "\"sampler_max_anisotropy\":" << stats.sampler_max_anisotropy << ","
           << "\"sampler_mip_lod_bias\":" << stats.sampler_mip_lod_bias << ","
           << "\"sampler_recreate_count\":" << stats.sampler_recreate_count << ","
           << "\"texture_details\":" << string_array_json(stats.texture_details) << ","
           << "\"skipped\":" << skipped_json(stats.skipped)
           << "}";
    return loaded.str();
}

static std::string loaded_payload(const RendererStats& stats) {
    return loaded_payload_for_event(stats, "loaded");
}

static std::string resources_loaded_payload(const RendererStats& stats) {
    return loaded_payload_for_event(stats, "resources_loaded");
}

static std::string error_payload(const std::string& message, const RendererStats& stats) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"error\","
        << "\"backend\":\"D3D11\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"batch_count\":" << stats.batch_count << ","
        << "\"vertex_count\":" << stats.vertex_count << ","
        << "\"texture_failures\":" << stats.texture_failures << ","
        << "\"failed_textures\":" << failed_textures_json(stats.failed_textures) << ","
        << "\"texture_bind_ms\":" << stats.texture_ms << ","
        << "\"geometry_upload_ms\":" << stats.geometry_ms << ","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"skipped\":" << skipped_json(stats.skipped)
        << "}";
    return out.str();
}

static std::string cleared_payload(const RendererStats& stats) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"cleared\","
        << "\"backend\":\"D3D11\","
        << "\"message\":\"Native D3D11 preview cleared\","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"texture_cache_bytes\":" << stats.texture_cache_bytes << ","
        << "\"live_texture_bytes\":" << stats.live_texture_bytes << ","
        << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
        << "\"process_private_bytes\":" << stats.process_private_bytes << ","
        << "\"frame_count\":" << stats.frame_count << ","
        << "\"render_request_count\":" << stats.render_request_count << ","
        << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
        << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
        << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
        << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\""
        << "}";
    return out.str();
}

static std::string closed_payload(const RendererStats& stats, const std::string& reason) {
    std::ostringstream out;
    out << "{"
        << "\"event\":\"closed\","
        << "\"backend\":\"D3D11\","
        << "\"reason\":\"" << json_escape(reason) << "\","
        << "\"texture_cache_entries\":" << stats.texture_cache_entries << ","
        << "\"texture_cache_releases\":" << stats.texture_cache_releases << ","
        << "\"estimated_texture_bytes\":" << stats.estimated_texture_bytes << ","
        << "\"process_working_set_bytes\":" << stats.process_working_set_bytes << ","
        << "\"process_private_bytes\":" << stats.process_private_bytes << ","
        << "\"frame_count\":" << stats.frame_count << ","
        << "\"render_request_count\":" << stats.render_request_count << ","
        << "\"render_suppressed_count\":" << stats.render_suppressed_count << ","
        << "\"mesh_edit_selection_event_count\":" << stats.mesh_edit_selection_event_count << ","
        << "\"parent_unresponsive_count\":" << stats.parent_unresponsive_count << ","
        << "\"parent_health\":\"" << json_escape(stats.parent_health) << "\""
        << "}";
    return out.str();
}

static HRESULT compile_shader(const char* source, const char* entry, const char* target, ID3DBlob** blob, std::string& error_text) {
    UINT flags = D3DCOMPILE_ENABLE_STRICTNESS;
#if defined(_DEBUG)
    flags |= D3DCOMPILE_DEBUG;
#endif
    ComPtr<ID3DBlob> errors;
    HRESULT hr = D3DCompile(source, strlen(source), nullptr, nullptr, nullptr, entry, target, flags, 0, blob, errors.GetAddressOf());
    if (FAILED(hr) && errors) {
        error_text.assign(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize());
    }
    return hr;
}

static HRESULT compile_shader(const std::string& source, const char* entry, const char* target, ID3DBlob** blob, std::string& error_text) {
    return compile_shader(source.c_str(), entry, target, blob, error_text);
}

static const char kShaderSourceCommon[] = R"(
cbuffer Constants : register(b0) {
    row_major float4x4 mvp;
    row_major float4x4 normal_world;
    float4 light_dir;
    float4 base_color_flip;
    float4 flags;
    float4 flags2;
    float4 material_params;
    float4 material_hints;
    float4 flags3;
    float4 render_tuning;
    float4 render_tuning2;
    float4 render_tuning3;
    float4 render_tuning4;
    float4 editor_tint;
    float4 flags4;
    float4 flags5;
    float4 emissive_params;
    float4 material_value_params;
    float4 material_color_params;
    float4 material_tint_params;
    float4 layer_params[4];
    float4 layer_tint[4];
    float4 layer_hints[4];
    float4 layer_flags[4];
};
Texture2D base_tex : register(t0);
Texture2D normal_tex : register(t1);
Texture2D material_tex : register(t2);
Texture2D occlusion_tex : register(t3);
Texture2D roughness_tex : register(t4);
Texture2D metalness_tex : register(t5);
Texture2D specular_tex : register(t6);
Texture2D height_tex : register(t7);
Texture2D detail_tex : register(t8);
Texture2D emissive_tex : register(t9);
Texture2D layer0_diffuse_tex : register(t10);
Texture2D layer1_diffuse_tex : register(t11);
Texture2D layer2_diffuse_tex : register(t12);
Texture2D layer3_diffuse_tex : register(t13);
Texture2D layer0_mask_tex : register(t14);
Texture2D layer1_mask_tex : register(t15);
Texture2D layer2_mask_tex : register(t16);
Texture2D layer3_mask_tex : register(t17);
Texture2D layer0_material_tex : register(t18);
Texture2D layer1_material_tex : register(t19);
Texture2D layer2_material_tex : register(t20);
Texture2D layer3_material_tex : register(t21);
Texture2D layer0_normal_tex : register(t22);
Texture2D layer1_normal_tex : register(t23);
Texture2D layer2_normal_tex : register(t24);
Texture2D layer3_normal_tex : register(t25);
Texture2D layer0_height_tex : register(t26);
Texture2D layer1_height_tex : register(t27);
Texture2D layer2_height_tex : register(t28);
Texture2D layer3_height_tex : register(t29);
SamplerState preview_sampler : register(s0);
struct VSIn {
    float3 position : POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
struct VSOut {
    float4 position : SV_POSITION;
    float3 normal : NORMAL;
    float3 color : COLOR0;
    float2 uv : TEXCOORD0;
    float3 tangent : TANGENT;
    float3 bitangent : BINORMAL;
};
float3 srgb_to_linear(float3 color) {
    return pow(saturate(color), 2.2);
}
float3 linear_to_srgb(float3 color) {
    return pow(saturate(color), 1.0 / 2.2);
}
float3 aces_tonemap(float3 color) {
    color = max(color, float3(0.0, 0.0, 0.0));
    return saturate((color * (2.51 * color + 0.03)) / (color * (2.43 * color + 0.59) + 0.14));
}
float ggx_distribution(float ndoth, float roughness) {
    float a = max(roughness * roughness, 0.035);
    float a2 = a * a;
    float denom = (ndoth * ndoth) * (a2 - 1.0) + 1.0;
    return a2 / max(3.14159265 * denom * denom, 0.0001);
}
float geometry_schlick_ggx(float ndotv, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) * 0.125;
    return ndotv / max(ndotv * (1.0 - k) + k, 0.0001);
}
float geometry_smith(float ndotv, float ndotl, float roughness) {
    return geometry_schlick_ggx(ndotv, roughness) * geometry_schlick_ggx(ndotl, roughness);
}
float3 fresnel_schlick(float costheta, float3 f0) {
    return f0 + (1.0 - f0) * pow(1.0 - saturate(costheta), 5.0);
}
float3 preview_environment_color(float3 reflected_view, float roughness) {
    float env_lobe = saturate((reflected_view.y * 0.55) + (reflected_view.z * -0.14) + 0.58);
    float horizon_band = pow(saturate(1.0 - abs(reflected_view.y) * 1.12), 2.2);
    float front_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.18, 0.36, -0.92)))), lerp(14.0, 4.0, roughness));
    float top_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.32, 0.88, -0.34)))), lerp(28.0, 7.0, roughness));
    float side_softbox = pow(saturate(dot(reflected_view, normalize(float3(0.82, 0.20, -0.54)))), lerp(18.0, 5.0, roughness));
    float back_softbox = pow(saturate(dot(reflected_view, normalize(float3(-0.72, 0.26, 0.64)))), lerp(18.0, 5.0, roughness));
    float opposite_softbox = pow(saturate(dot(reflected_view, normalize(float3(0.58, 0.30, 0.76)))), lerp(20.0, 6.0, roughness));
    float dark_band = pow(saturate(1.0 - abs(reflected_view.x * 1.8 + reflected_view.y * 0.35)), 3.2) * saturate(0.85 - reflected_view.z);
    float3 env_color = lerp(float3(0.10, 0.11, 0.13), float3(0.82, 0.88, 0.98), env_lobe);
    env_color = lerp(env_color, env_color * float3(0.54, 0.56, 0.60), dark_band * (1.0 - roughness) * 0.32);
    env_color += horizon_band * float3(0.30, 0.32, 0.36);
    env_color += front_softbox.xxx * float3(0.78, 0.86, 0.98);
    env_color += top_softbox.xxx * float3(0.92, 0.86, 0.68);
    env_color += side_softbox.xxx * float3(0.48, 0.58, 0.76);
    env_color += back_softbox.xxx * float3(0.44, 0.52, 0.66);
    env_color += opposite_softbox.xxx * float3(0.38, 0.46, 0.60);
    return env_color;
}
float wrapped_ndotl(float3 normal_value, float3 light_value, float wrap_amount) {
    float wrap = saturate(wrap_amount);
    return saturate((dot(normalize(normal_value), normalize(light_value)) + wrap) / (1.0 + wrap));
}
VSOut vs_main(VSIn input) {
    VSOut output;
    output.position = mul(float4(input.position, 1.0), mvp);
    output.normal = normalize(mul(float4(input.normal, 0.0), normal_world).xyz);
    output.color = input.color;
    output.uv = input.uv;
    output.tangent = normalize(mul(float4(input.tangent, 0.0), normal_world).xyz);
    output.bitangent = normalize(mul(float4(input.bitangent, 0.0), normal_world).xyz);
    return output;
}
float select_mask_channel(float4 sample_value, float channel_value) {
    int mask_channel = (int)round(saturate(channel_value / 3.0) * 3.0);
    return mask_channel == 1 ? sample_value.g : (mask_channel == 2 ? sample_value.b : (mask_channel == 3 ? sample_value.a : sample_value.r));
}
float3 blend_sampled_normal(float3 base_n, float3 tangent, float3 bitangent, float3 sampled, float strength, float invert_y) {
    float2 xy = sampled.xy * 2.0 - 1.0;
    if (invert_y > 0.5) {
        xy.y = -xy.y;
    }
    float z = sqrt(saturate(1.0 - dot(xy, xy)));
    float3 mapped = normalize(float3(xy, z));
    float3 normal_mapped = normalize(tangent * mapped.x + bitangent * mapped.y + base_n * mapped.z);
    return normalize(lerp(base_n, normal_mapped, saturate(strength)));
}
)";

static const char kShaderSourcePixelMaterial[] = R"(
float4 ps_main(VSOut input) : SV_TARGET {
    float2 uv = input.uv;
    if (base_color_flip.w > 0.5) {
        uv.y = 1.0 - uv.y;
    }
    uv *= max(material_value_params.xy, float2(0.05, 0.05));
    float preview_brightness = max(material_value_params.z, 0.1);
    float preview_contrast = max(material_color_params.x, 0.01);
    float preview_saturation = max(material_color_params.y, 0.0);
    float preview_gamma = max(material_color_params.z, 0.01);
    float3 preview_tint_color = max(material_tint_params.rgb, float3(0.0, 0.0, 0.0));
    float3 albedo = srgb_to_linear(max(input.color, base_color_flip.rgb));
    float base_alpha = 1.0;
    float early_category_code = flags5.x;
    bool early_category_metal = early_category_code > 0.5 && early_category_code < 1.5;
    if (flags.x > 0.5) {
        float4 base_sample = base_tex.Sample(preview_sampler, uv);
        albedo = saturate(base_sample.rgb);
        base_alpha = base_sample.a;
        if (flags4.x > 0.001) {
            float3 preview_tint = saturate(base_color_flip.rgb);
            float tint_luma = max(dot(preview_tint, float3(0.299, 0.587, 0.114)), 0.08);
            float3 tint_bias = clamp(preview_tint / tint_luma, float3(0.38, 0.38, 0.38), float3(1.72, 1.72, 1.72));
            float tint_chroma = max(preview_tint.r, max(preview_tint.g, preview_tint.b)) - min(preview_tint.r, min(preview_tint.g, preview_tint.b));
            float neutral_metal_tint = early_category_metal ? saturate((0.12 - tint_chroma) * 8.0) : 0.0;
            float strength = saturate(flags4.x * (early_category_metal ? lerp(0.05, 1.25, neutral_metal_tint) : 1.0));
            float albedo_luma = dot(albedo, float3(0.299, 0.587, 0.114));
            float lifted_luma = saturate(albedo_luma * (1.05 + strength * 0.35) + 0.10 * strength);
            float3 multiplied = saturate(albedo * tint_bias);
            float3 colorized = saturate(lifted_luma.xxx * tint_bias);
            float neutral_metal_luma = saturate(albedo_luma * (0.55 + tint_luma * 0.45) + 0.012);
            colorized = lerp(colorized, saturate(neutral_metal_luma.xxx * tint_bias), neutral_metal_tint);
            float colorize_strength = lerp(0.58, 0.96, neutral_metal_tint);
            albedo = lerp(albedo, lerp(multiplied, colorized, colorize_strength), strength);
        }
    }
    albedo = saturate(albedo * preview_brightness);
    albedo *= preview_tint_color;
    float albedo_luma_adjusted = dot(albedo, float3(0.299, 0.587, 0.114));
    albedo = saturate(albedo_luma_adjusted.xxx + (albedo - albedo_luma_adjusted.xxx) * preview_saturation);
    albedo = saturate((albedo - 0.5) * preview_contrast + 0.5);
    if (abs(preview_gamma - 1.0) > 0.001) {
        albedo = pow(saturate(albedo), float3(preview_gamma, preview_gamma, preview_gamma));
    }
    albedo = max(albedo, float3(0.012, 0.012, 0.012));
    if (flags3.z > 0.5 && base_alpha < max(flags3.w, 0.001)) {
        discard;
    }
    float debug_mode = flags4.y;
    if (debug_mode > 1.5 && debug_mode < 2.5) {
        float2 checker_uv = frac(uv * 16.0);
        float checker = abs((checker_uv.x > 0.5 ? 1.0 : 0.0) - (checker_uv.y > 0.5 ? 1.0 : 0.0));
        return float4(lerp(float3(0.04, 0.05, 0.06), float3(0.78, 0.88, 1.0), checker), 1.0);
    }
    if (debug_mode > 0.5 && debug_mode < 1.5) {
        float3 inspection_albedo = saturate(albedo * 1.18 + float3(0.018, 0.018, 0.018));
        return float4(linear_to_srgb(inspection_albedo), 1.0);
    }
    if (debug_mode > 2.5 && debug_mode < 3.5) {
        return float4(base_alpha.xxx, 1.0);
    }
    if (debug_mode > 3.5 && debug_mode < 4.5) {
        float seed = frac(flags4.z * 0.6180339 + 0.17);
        return float4(frac(seed + 0.23), frac(seed * 2.31 + 0.47), frac(seed * 3.73 + 0.71), 1.0);
    }
    float layer_alpha[4] = {0.0, 0.0, 0.0, 0.0};
#define APPLY_ALBEDO_LAYER(ID, DIFFUSE_TEX, MASK_TEX) \
    if (layer_flags[ID].x > 0.5) { \
        float4 mask_sample = float4(1.0, 1.0, 1.0, 1.0); \
        if (layer_flags[ID].y > 0.5) { \
            mask_sample = MASK_TEX.Sample(preview_sampler, uv); \
        } \
        float mask_value = select_mask_channel(mask_sample, layer_params[ID].x); \
        float tint_alpha = saturate(layer_tint[ID].a) * (early_category_metal ? 0.18 : 1.0); \
        layer_alpha[ID] = saturate(mask_value * layer_params[ID].y * tint_alpha); \
        float3 layer_sample = DIFFUSE_TEX.Sample(preview_sampler, uv).rgb; \
        float3 layer_tint_rgb = saturate(layer_tint[ID].rgb); \
        float layer_tint_luma = max(dot(layer_tint_rgb, float3(0.299, 0.587, 0.114)), 0.08); \
        float3 layer_tint_bias = clamp(layer_tint_rgb / layer_tint_luma, float3(0.32, 0.32, 0.32), float3(2.15, 2.15, 2.15)); \
        float layer_luma = dot(layer_sample, float3(0.299, 0.587, 0.114)); \
        float layer_lifted_luma = saturate(layer_luma * (1.08 + layer_params[ID].y * 0.24) + 0.06 * layer_params[ID].y); \
        float3 layer_multiplied = saturate(layer_sample * layer_tint_bias); \
        float3 layer_colorized = saturate(layer_lifted_luma.xxx * layer_tint_bias); \
        float layer_chroma = max(layer_tint_rgb.r, max(layer_tint_rgb.g, layer_tint_rgb.b)) - min(layer_tint_rgb.r, min(layer_tint_rgb.g, layer_tint_rgb.b)); \
        float layer_colorize_strength = saturate(0.18 + layer_chroma * 1.35) * (early_category_metal ? 0.08 : 1.0); \
        float strong_dye_strength = saturate((layer_chroma - 0.38) * 1.65) * (early_category_metal ? 0.05 : 1.0); \
        float3 dye_authority_color = saturate(layer_tint_rgb * (0.62 + layer_lifted_luma * 0.70)); \
        layer_alpha[ID] = saturate(layer_alpha[ID] * (1.0 + strong_dye_strength * 0.35)); \
        float3 layer_color = lerp(lerp(layer_multiplied, layer_colorized, layer_colorize_strength), dye_authority_color, strong_dye_strength); \
        albedo = lerp(albedo, layer_color, layer_alpha[ID]); \
    }
    APPLY_ALBEDO_LAYER(0, layer0_diffuse_tex, layer0_mask_tex)
    APPLY_ALBEDO_LAYER(1, layer1_diffuse_tex, layer1_mask_tex)
    APPLY_ALBEDO_LAYER(2, layer2_diffuse_tex, layer2_mask_tex)
    APPLY_ALBEDO_LAYER(3, layer3_diffuse_tex, layer3_mask_tex)
#undef APPLY_ALBEDO_LAYER
    if (debug_mode > 6.5 && debug_mode < 7.5) {
        return float4(layer_alpha[0], layer_alpha[1], layer_alpha[2], 1.0);
    }
    float3 n = normalize(input.normal);
    float3 t = input.tangent;
    float3 b = input.bitangent;
    if (dot(t, t) < 1e-5) {
        t = float3(1.0, 0.0, 0.0);
    } else {
        t = normalize(t);
    }
    if (dot(b, b) < 1e-5) {
        b = normalize(cross(n, t));
    } else {
        b = normalize(b);
    }
    if (flags.y > 0.5) {
        float3 sampled = normal_tex.Sample(preview_sampler, uv).xyz;
        float2 xy = sampled.xy * 2.0 - 1.0;
        if (flags3.y > 0.5) {
            xy.y = -xy.y;
        }
        float z = sqrt(saturate(1.0 - dot(xy, xy)));
        float3 mapped = normalize(float3(xy, z));
        float3 normal_mapped = normalize(t * mapped.x + b * mapped.y + n * mapped.z);
        n = normalize(lerp(n, normal_mapped, saturate(material_params.x)));
    }
#define APPLY_NORMAL_LAYER(ID, NORMAL_TEX) \
    if (layer_flags[ID].w > 0.5 && layer_alpha[ID] > 0.001) { \
        n = blend_sampled_normal(n, t, b, NORMAL_TEX.Sample(preview_sampler, uv).xyz, material_params.x * layer_alpha[ID] * 0.65, flags3.y); \
    }
    APPLY_NORMAL_LAYER(0, layer0_normal_tex)
    APPLY_NORMAL_LAYER(1, layer1_normal_tex)
    APPLY_NORMAL_LAYER(2, layer2_normal_tex)
    APPLY_NORMAL_LAYER(3, layer3_normal_tex)
#undef APPLY_NORMAL_LAYER
    if (debug_mode > 4.5 && debug_mode < 5.5) {
        return float4(n * 0.5 + 0.5, 1.0);
    }
    float ao = 1.0;
    float roughness = 0.55;
    float specular = 0.15;
    float metalness = 0.0;
    float user_metalness_scale = max(render_tuning3.z, 0.0);
    bool explicit_material_authority_hint = material_hints.x > 0.02 || material_hints.y > 0.02 || material_hints.z > 0.02 || material_hints.w > 0.02;
    if (material_hints.x > 0.02) {
        roughness = lerp(roughness, material_hints.x, 0.72);
    }
    if (material_hints.y > 0.02) {
        metalness = max(metalness, saturate(material_hints.y * user_metalness_scale));
    }
    if (material_hints.z > 0.02) {
        specular = max(specular, material_hints.z);
    }
    float family_code = flags4.w;
    float category_code = flags5.x;
    float category_confidence = saturate(flags5.y);
    bool category_metal = category_code > 0.5 && category_code < 1.5;
    bool category_leather = category_code > 1.5 && category_code < 2.5;
    bool category_wood = category_code > 2.5 && category_code < 3.5;
    bool category_cloth = category_code > 3.5 && category_code < 4.5;
    bool category_skin = category_code > 4.5 && category_code < 5.5;
    bool category_hair = category_code > 5.5 && category_code < 6.5;
    bool category_glass = category_code > 6.5 && category_code < 7.5;
    bool category_gem = category_code > 7.5 && category_code < 8.5;
    bool category_stone = category_code > 8.5 && category_code < 9.5;
    bool category_eye = category_code > 9.5 && category_code < 10.5;
    bool category_tooth = category_code > 10.5 && category_code < 11.5;
    bool glossy_nonmetal = category_glass || category_gem || category_eye;
    bool conservative_nonmetal = category_leather || category_wood || category_cloth || category_skin || category_hair || category_stone || category_tooth;
    bool known_nonmetal = conservative_nonmetal || glossy_nonmetal;
    float metal_scale = 1.0;
    float specular_scale = 1.0;
    float roughness_bias = 0.0;
)" R"(
    if (family_code > 0.5 && family_code < 1.5) {
        metal_scale = 0.12;
        specular_scale = 1.20;
        roughness_bias = 0.06;
    } else if (family_code > 1.5 && family_code < 2.5) {
        metal_scale = 0.05;
        specular_scale = 1.45;
        roughness_bias = -0.08;
    } else if (family_code > 2.5 && family_code < 3.5) {
        metal_scale = 0.28;
        specular_scale = 0.95;
        roughness_bias = 0.10;
    } else if (family_code > 3.5 && family_code < 4.5) {
        metal_scale = 1.15;
        specular_scale = 1.35;
        roughness_bias = -0.04;
    } else if (family_code > 4.5 && family_code < 5.5) {
        metal_scale = 1.05;
        specular_scale = 1.20;
        roughness_bias = -0.02;
    } else if (family_code > 5.5 && family_code < 6.5) {
        metal_scale = 0.55;
        specular_scale = 1.15;
        roughness_bias = -0.03;
    }
    float category_metal_cap = category_metal ? 1.0 : (known_nonmetal ? 0.0 : lerp(0.12, 0.32, category_confidence));
    float category_specular_cap = category_metal ? 1.0 : (category_glass ? 0.42 : (category_gem ? 0.48 : (category_eye ? 0.44 : (category_leather ? 0.14 : (category_wood ? 0.16 : (category_cloth ? 0.055 : (category_skin ? 0.20 : (category_hair ? 0.22 : (category_stone ? 0.10 : (category_tooth ? 0.18 : 0.18))))))))));
    float category_env_scale = category_metal ? 0.94 : (category_glass ? 0.26 : (category_gem ? 0.30 : (category_eye ? 0.24 : (category_leather ? 0.06 : (category_wood ? 0.06 : (category_cloth ? 0.025 : (category_skin ? 0.075 : (category_hair ? 0.08 : (category_stone ? 0.04 : (category_tooth ? 0.08 : 0.08))))))))));
    float category_roughness_floor = category_metal ? 0.16 : (category_glass ? 0.30 : (category_gem ? 0.26 : (category_eye ? 0.30 : (category_leather ? 0.76 : (category_wood ? 0.70 : (category_cloth ? 0.84 : (category_skin ? 0.58 : (category_hair ? 0.64 : (category_stone ? 0.82 : (category_tooth ? 0.58 : 0.66))))))))));
    if (explicit_material_authority_hint && !conservative_nonmetal) {
        float gloss_hint = saturate((1.0 - material_hints.x) * 0.85 + material_hints.z * 0.45);
        category_specular_cap = max(category_specular_cap, max(material_hints.z, gloss_hint));
        category_env_scale = max(category_env_scale, lerp(0.12, 0.42, gloss_hint));
        category_roughness_floor = min(category_roughness_floor, lerp(0.08, 0.42, saturate(material_hints.x)));
    }
    float category_metal_fallback = category_metal ? saturate(lerp(0.28, 0.62, category_confidence) * user_metalness_scale) : 0.0;
    if (category_metal && material_hints.y <= 0.02 && flags.z <= 0.5 && flags2.z <= 0.5) {
        metalness = max(metalness, category_metal_fallback);
        specular = max(specular, lerp(0.34, 0.62, category_confidence));
        roughness = min(roughness, lerp(0.46, 0.28, category_confidence));
    }
    metal_scale *= user_metalness_scale * category_metal_cap;
    specular_scale *= category_specular_cap;
    if (conservative_nonmetal) {
        roughness = max(roughness, category_roughness_floor);
        specular = min(specular, 0.28 * max(category_specular_cap, 0.20));
    }
    if (!conservative_nonmetal) {
        specular = max(specular, render_tuning.z);
    }
    if (flags.z > 0.5) {
        float4 m = material_tex.Sample(preview_sampler, uv);
        ao = min(ao, max(category_skin ? 0.72 : 0.58, m.r));
        roughness = saturate(m.g);
        metalness = max(metalness, saturate(m.b) * (category_metal ? 0.96 : 0.65) * metal_scale);
        specular = saturate(max(m.a, m.b * 0.55) * specular_scale);
    }
    if (flags2.x > 0.5) {
        ao = min(ao, max(category_skin ? 0.72 : 0.58, occlusion_tex.Sample(preview_sampler, uv).r));
    }
    if (flags2.y > 0.5) {
        roughness = saturate(roughness_tex.Sample(preview_sampler, uv).r);
    }
    if (flags2.z > 0.5) {
        metalness = saturate(metalness_tex.Sample(preview_sampler, uv).r * metal_scale);
    }
    if (flags2.w > 0.5) {
        float3 spec_sample = specular_tex.Sample(preview_sampler, uv).rgb;
        float spec_value = max(spec_sample.r, max(spec_sample.g, spec_sample.b));
        specular = saturate(max(specular, spec_value * 0.88 * specular_scale));
        if (flags2.y < 0.5) {
            roughness = min(roughness, lerp(0.72, 0.24, spec_value));
        }
    }
    if (flags3.x > 0.5) {
        float3 detail_sample = detail_tex.Sample(preview_sampler, uv).rgb;
        float detail_value = max(detail_sample.r, max(detail_sample.g, detail_sample.b));
        roughness = saturate(lerp(roughness, roughness * (0.86 + detail_value * 0.30), 0.36));
        if (flags2.w < 0.5) {
            specular = saturate(max(specular, detail_value * 0.16));
        }
    }
#define APPLY_MATERIAL_LAYER(ID, MATERIAL_TEX) \
    if (layer_flags[ID].z > 0.5 && layer_alpha[ID] > 0.001) { \
        float4 lm = MATERIAL_TEX.Sample(preview_sampler, uv); \
        roughness = lerp(roughness, saturate(max(lm.g, layer_hints[ID].x)), saturate(layer_alpha[ID] * 0.58)); \
        metalness = max(metalness, saturate(max(lm.b * 0.72, layer_hints[ID].y) * metal_scale) * layer_alpha[ID]); \
        specular = max(specular, saturate(max(max(lm.a, lm.b * 0.55), layer_hints[ID].z) * specular_scale) * layer_alpha[ID]); \
    }
    APPLY_MATERIAL_LAYER(0, layer0_material_tex)
    APPLY_MATERIAL_LAYER(1, layer1_material_tex)
    APPLY_MATERIAL_LAYER(2, layer2_material_tex)
    APPLY_MATERIAL_LAYER(3, layer3_material_tex)
#undef APPLY_MATERIAL_LAYER
    if (explicit_material_authority_hint) {
        if (material_hints.x > 0.02) {
            roughness = lerp(roughness, material_hints.x, 0.55);
        }
        if (material_hints.z > 0.02) {
            specular = max(specular, material_hints.z);
        }
    }
    if (debug_mode > 5.5 && debug_mode < 6.5) {
        return float4(saturate(ao), saturate(roughness), saturate(specular), 1.0);
    }
    bool promoted_material_response = flags5.z > 0.5;
    bool direct_metal_response = category_metal && (metalness > 0.12 || material_hints.y > 0.16 || flags2.z > 0.5 || promoted_material_response);
    if (direct_metal_response) {
        category_metal_cap = max(category_metal_cap, 0.96);
        category_env_scale = max(category_env_scale, 0.86);
        category_specular_cap = max(category_specular_cap, 0.82);
        category_roughness_floor = min(category_roughness_floor, 0.08);
        metalness = max(metalness, category_metal_fallback);
        specular = max(specular, lerp(0.42, 0.72, category_confidence));
        roughness = min(roughness, lerp(0.34, 0.16, category_confidence));
    }
    roughness = saturate(roughness + roughness_bias + render_tuning3.y);
    roughness = max(roughness, category_roughness_floor);
    metalness = min(metalness, category_metal_cap);
    ao = saturate(1.0 - ((1.0 - ao) * render_tuning3.x));
    float nonmetal_specular_cap = conservative_nonmetal ? category_specular_cap : max(0.18, category_specular_cap);
    specular = min(specular, min(max(max(render_tuning.w, render_tuning.z), lerp(0.30, 0.92, metalness)), category_metal ? 0.96 : nonmetal_specular_cap));
    float height_value = 0.5;
    if (flags.w > 0.5) {
        height_value = height_tex.Sample(preview_sampler, uv).r;
        float2 duv_x = ddx(uv);
        float2 duv_y = ddy(uv);
        if (dot(duv_x, duv_x) < 1e-8) {
            duv_x = float2(1.0 / 1024.0, 0.0);
        }
        if (dot(duv_y, duv_y) < 1e-8) {
            duv_y = float2(0.0, 1.0 / 1024.0);
        }
        float hx = height_tex.Sample(preview_sampler, uv + duv_x).r - height_tex.Sample(preview_sampler, uv - duv_x).r;
        float hy = height_tex.Sample(preview_sampler, uv + duv_y).r - height_tex.Sample(preview_sampler, uv - duv_y).r;
        float height_strength = saturate((material_params.y + material_hints.w * 0.04) * 8.0);
        float3 height_normal = normalize(n - t * hx * height_strength * 2.4 + b * hy * height_strength * 2.4);
        n = normalize(lerp(n, height_normal, height_strength));
        float relief = (height_value - 0.5) * saturate(material_params.y * 10.0);
        roughness = saturate(roughness - relief * 0.10);
    }
#define APPLY_HEIGHT_LAYER(ID, HEIGHT_TEX) \
    if (layer_params[ID].z > 0.5 && layer_alpha[ID] > 0.001) { \
        float layer_height_value = HEIGHT_TEX.Sample(preview_sampler, uv).r; \
        height_value = lerp(height_value, layer_height_value, layer_alpha[ID]); \
        roughness = saturate(roughness - (layer_height_value - 0.5) * saturate(layer_hints[ID].w * layer_alpha[ID]) * 0.12); \
    }
    APPLY_HEIGHT_LAYER(0, layer0_height_tex)
    APPLY_HEIGHT_LAYER(1, layer1_height_tex)
    APPLY_HEIGHT_LAYER(2, layer2_height_tex)
    APPLY_HEIGHT_LAYER(3, layer3_height_tex)
#undef APPLY_HEIGHT_LAYER
    if (conservative_nonmetal) {
        roughness = max(roughness, category_roughness_floor);
        metalness = min(metalness, category_metal_cap);
        specular = min(specular, category_specular_cap);
    }
    if (debug_mode > 7.5 && debug_mode < 8.5) {
        return float4(saturate(metalness).xxx, 1.0);
    }
    if (debug_mode > 8.5 && debug_mode < 9.5) {
        return float4(saturate(roughness).xxx, 1.0);
    }
    if (debug_mode > 9.5 && debug_mode < 10.5) {
        return float4(saturate(specular), saturate(1.0 - roughness), saturate(metalness), 1.0);
    }
)";

static const char kShaderSourcePixelLighting[] = R"(
    roughness = clamp(roughness, 0.035, 0.98);
    float smoothness = saturate(1.0 - roughness);
    float texture_luma = dot(albedo, float3(0.299, 0.587, 0.114));
    float ao_weight = saturate(render_tuning3.x) * (category_metal ? 1.00 : (glossy_nonmetal ? 0.82 : (category_skin ? 0.58 : (conservative_nonmetal ? 0.62 : 0.78))));
    float stable_ao = lerp(1.0, saturate(ao), ao_weight);
    float lift = category_metal ? 0.020 : (category_skin ? 0.025 : (category_hair ? 0.035 : 0.030));
    float cloth_high_luma_guard = category_cloth ? saturate((texture_luma - 0.82) * 4.0) : 0.0;
    float cloth_texture_boost = category_cloth ? lerp(0.03, -0.02, cloth_high_luma_guard) : 0.0;
    float3 material_reference_albedo = saturate(albedo * (1.03 + cloth_texture_boost) + lift.xxx * saturate(1.0 - texture_luma));
    if (category_skin) {
        material_reference_albedo = saturate(material_reference_albedo * 1.04 + float3(0.004, 0.002, 0.001));
    }
    if (category_cloth && cloth_high_luma_guard > 0.001) {
        float3 cloth_highlight_cap = float3(0.94, 0.91, 0.84);
        material_reference_albedo = lerp(material_reference_albedo, min(material_reference_albedo, cloth_highlight_cap), cloth_high_luma_guard * 0.35);
    }
    if (material_hints.w > 0.02 && flags.w <= 0.5) {
        float relief_edge = saturate((abs(ddx(texture_luma)) + abs(ddy(texture_luma))) * 34.0);
        material_reference_albedo = saturate(
            material_reference_albedo * (1.0 + relief_edge * saturate(material_hints.w) * 0.24)
            - (1.0 - relief_edge) * saturate(material_hints.w) * 0.018);
    }
    if (explicit_material_authority_hint && material_hints.x > 0.62 && !conservative_nonmetal) {
        float matte_preview = saturate((material_hints.x - 0.62) * 2.63);
        float luma = dot(material_reference_albedo, float3(0.299, 0.587, 0.114));
        float3 flattened = lerp(material_reference_albedo, luma.xxx, 0.42);
        material_reference_albedo = lerp(material_reference_albedo, flattened * 0.88 + 0.018.xxx, matte_preview * 0.58);
    }
    if (category_metal) {
        float3 metal_tint = saturate(base_color_flip.rgb);
        float metal_tint_luma = max(dot(metal_tint, float3(0.299, 0.587, 0.114)), 0.08);
        float3 metal_tint_bias = clamp(metal_tint / metal_tint_luma, float3(0.58, 0.58, 0.58), float3(1.42, 1.42, 1.42));
        material_reference_albedo = saturate(lerp(material_reference_albedo, material_reference_albedo * metal_tint_bias, 0.34));
    }
    float3 view_dir = normalize(float3(0.0, 0.0, -1.0));
    float3 key_dir = normalize(light_dir.xyz);
    float3 fill_dir = normalize(float3(-key_dir.x * 0.55, 0.55, -0.80));
    float3 half_dir = normalize(key_dir + view_dir);
    float key_light = wrapped_ndotl(n, key_dir, render_tuning2.z);
    float fill_light = wrapped_ndotl(n, fill_dir, 0.82);
    float camera_shape = saturate(abs(dot(n, view_dir)));
    float rim_shape = pow(saturate(1.0 - camera_shape), lerp(2.4, 1.2, smoothness));
    float ambient_floor = category_metal ? 0.24 : (category_skin ? 0.60 : (conservative_nonmetal ? 0.58 : 0.52));
    float diffuse_depth = saturate(ambient_floor * render_tuning.x + render_tuning.y * (key_light * 0.58 + fill_light * 0.30 + rim_shape * 0.12));
    float depth_authority = category_metal ? 1.00 : (glossy_nonmetal ? 0.72 : (category_skin ? 0.40 : (category_hair ? 0.38 : (category_cloth ? 0.46 : (category_leather ? 0.52 : 0.50)))));
    diffuse_depth = lerp(1.0, diffuse_depth, depth_authority);
    float metal_cue = category_metal ? saturate(metalness * lerp(0.18, 0.58, smoothness)) : 0.0;
    float glossy_cue = glossy_nonmetal ? saturate(specular * lerp(0.06, 0.20, smoothness)) : 0.0;
    float authority_gloss_cue = (explicit_material_authority_hint && !conservative_nonmetal)
        ? saturate((1.0 - material_hints.x) * 0.55 + material_hints.z * 0.75 + material_hints.y * 0.35)
        : 0.0;
    float nonmetal_texture_scale = conservative_nonmetal ? 1.03 : 1.0;
    float metal_strength = category_metal ? saturate(metalness) : 0.0;
    float metal_diffuse_scale = lerp(1.0, 0.34, metal_strength);
    float3 color = material_reference_albedo * stable_ao * nonmetal_texture_scale * diffuse_depth * metal_diffuse_scale;
    color += material_reference_albedo * metal_cue * 0.16;
    color += material_reference_albedo * glossy_cue * 0.22;
    color += material_reference_albedo * authority_gloss_cue * (0.035 + rim_shape * 0.16);
    float ndotv = saturate(camera_shape);
    float ndoth = saturate(dot(n, half_dir));
    float spec_power = lerp(render_tuning2.x, render_tuning2.y, smoothness);
    float direct_lobe = pow(ndoth, spec_power) * saturate(key_light * 1.25);
    float broad_metal_lobe = category_metal ? pow(ndoth, lerp(7.0, 22.0, smoothness)) * saturate(key_light * 0.85 + rim_shape * 0.45) : 0.0;
    float3 f0 = lerp(float3(0.035, 0.035, 0.035), material_reference_albedo, saturate(metalness));
    float3 direct_specular = fresnel_schlick(ndotv, f0) * (direct_lobe + broad_metal_lobe * 1.05) * render_tuning.w;
    float direct_specular_scale = category_metal ? (1.10 + metalness * 0.85) : (glossy_nonmetal ? 0.18 : (conservative_nonmetal ? 0.025 : 0.08));
    color += direct_specular * direct_specular_scale;
    float3 reflected_view = normalize(reflect(-view_dir, n));
    float3 env_reflection = preview_environment_color(reflected_view, roughness);
    if (category_metal) {
        float3 metal_tint = saturate(base_color_flip.rgb);
        float tint_chroma = max(metal_tint.r, max(metal_tint.g, metal_tint.b)) - min(metal_tint.r, min(metal_tint.g, metal_tint.b));
        float tint_luma = max(dot(metal_tint, float3(0.299, 0.587, 0.114)), 0.08);
        float3 tint_bias = clamp(metal_tint / tint_luma, float3(0.70, 0.70, 0.70), float3(1.36, 1.36, 1.36));
        env_reflection *= lerp(float3(1.0, 1.0, 1.0), tint_bias, saturate(tint_chroma * 0.44));
    }
    float env_material_scale = category_metal ? (0.55 + metalness * lerp(0.45, 1.10, smoothness)) : (glossy_nonmetal ? 0.18 : (conservative_nonmetal ? 0.018 : 0.08));
    env_material_scale = max(env_material_scale, authority_gloss_cue * 0.32);
    float3 env_fresnel = fresnel_schlick(ndotv, f0);
    color += env_reflection * env_fresnel * render_tuning3.w * category_env_scale * env_material_scale;
    if (emissive_params.a > 0.001) {
        float encoded_emissive = emissive_params.a;
        bool has_emissive_tex = encoded_emissive > 1.5;
        float emissive_intensity = saturate(has_emissive_tex ? encoded_emissive - 2.0 : encoded_emissive);
        float emissive_mask = 1.0;
        float3 emissive_color = emissive_params.rgb;
        if (has_emissive_tex) {
            float4 emissive_sample = emissive_tex.Sample(preview_sampler, uv);
            emissive_mask = max(emissive_sample.r, max(emissive_sample.g, emissive_sample.b));
            emissive_color = max(emissive_color, emissive_sample.rgb);
        }
        float emissive_strength = emissive_intensity * saturate(emissive_mask) * render_tuning4.x;
        color += emissive_color * emissive_strength * 0.85;
    }
    color = lerp(color, editor_tint.rgb, saturate(editor_tint.a));
    float tone_exposure = max(render_tuning4.y, 0.05);
    float tone_contrast = max(render_tuning4.z, 0.10);
    float tone_gamma = max(render_tuning4.w, 0.20);
    float3 mapped = aces_tonemap(color * tone_exposure);
    mapped = saturate((mapped - 0.5) * tone_contrast + 0.5);
    mapped = pow(mapped, float3(tone_gamma, tone_gamma, tone_gamma));
    return float4(linear_to_srgb(mapped), 1.0);
}
)";

static const std::string& shader_source() {
    static const std::string source =
        std::string(kShaderSourceCommon) + kShaderSourcePixelMaterial + kShaderSourcePixelLighting;
    return source;
}

static const std::string& kShaderSource = shader_source();

static const char* kVertexDotShaderSource = R"(
struct DotIn {
    float3 center : TEXCOORD0;
    float2 radius : TEXCOORD1;
    float4 color : COLOR0;
};
struct DotOut {
    float4 position : SV_POSITION;
    float4 color : COLOR0;
    float2 local : TEXCOORD0;
};
DotOut vs_dot(uint vertex_id : SV_VertexID, DotIn input) {
    float2 corners[6] = {
        float2(-1.0, -1.0), float2( 1.0, -1.0), float2( 1.0,  1.0),
        float2(-1.0, -1.0), float2( 1.0,  1.0), float2(-1.0,  1.0)
    };
    float2 local = corners[vertex_id];
    DotOut output;
    output.position = float4(input.center.xy + local * input.radius, input.center.z, 1.0);
    output.color = input.color;
    output.local = local;
    return output;
}
float4 ps_dot(DotOut input) : SV_Target {
    if (dot(input.local, input.local) > 1.0) discard;
    return input.color;
}
)";

static const char* kOverlayPixelShaderSource = R"(
float4 ps_overlay(VSOut input) : SV_Target {
    return float4(saturate(input.color), 1.0);
}
)";

class Renderer {
public:
    Renderer(
        HWND hwnd,
        const Args& args,
        std::vector<PreviewBatch> batches,
        std::vector<ClothCollider> cloth_colliders,
        SkeletonOverlayState skeleton_overlay,
        RendererStats& stats,
        ViewSettings view_settings,
        RenderTuning render_tuning,
        std::string display_mode)
        : hwnd_(hwnd),
          args_(args),
          batches_(std::move(batches)),
          cloth_colliders_(std::move(cloth_colliders)),
          skeleton_overlay_(std::move(skeleton_overlay)),
          stats_(stats),
          view_settings_(view_settings),
          render_tuning_(render_tuning),
          display_mode_(normalize_display_mode(std::move(display_mode), "replacement_only")) {
        stats_.sampler_max_anisotropy = std::clamp(render_tuning_.max_anisotropy, 1, 16);
        stats_.sampler_mip_lod_bias = std::clamp(render_tuning_.mip_lod_bias, -2.0f, 1.0f);
    }

    ~Renderer() {
        if (!batches_.empty() || !srv_cache_.empty() || !texture_info_cache_.empty() || estimated_texture_bytes_ > 0) {
            release_model_resources("destructor");
        }
    }

    bool initialize() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        width_ = std::max<LONG>(1, rect.right - rect.left);
        height_ = std::max<LONG>(1, rect.bottom - rect.top);

        D3D_FEATURE_LEVEL requested[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
        HRESULT hr = E_FAIL;
        const UINT sample_candidates[] = {4, 2, 1};
        for (UINT sample_count : sample_candidates) {
            DXGI_SWAP_CHAIN_DESC swap_desc{};
            swap_desc.BufferCount = 2;
            swap_desc.BufferDesc.Width = static_cast<UINT>(width_);
            swap_desc.BufferDesc.Height = static_cast<UINT>(height_);
            swap_desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            swap_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
            swap_desc.OutputWindow = hwnd_;
            swap_desc.SampleDesc.Count = sample_count;
            swap_desc.SampleDesc.Quality = 0;
            swap_desc.Windowed = TRUE;
            swap_desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
            swap_chain_.Reset();
            device_.Reset();
            context_.Reset();
            hr = D3D11CreateDeviceAndSwapChain(
                nullptr,
                D3D_DRIVER_TYPE_HARDWARE,
                nullptr,
                0,
                requested,
                2,
                D3D11_SDK_VERSION,
                &swap_desc,
                swap_chain_.GetAddressOf(),
                device_.GetAddressOf(),
                &feature_level_,
                context_.GetAddressOf());
            if (SUCCEEDED(hr)) {
                msaa_sample_count_ = sample_count;
                break;
            }
        }
        if (FAILED(hr)) {
            stats_.skipped.push_back("D3D11CreateDeviceAndSwapChain failed");
            return false;
        }
        return create_render_targets() && create_pipeline() && upload_batches();
    }

    void request_render() {
        ++render_request_count_;
        stats_.render_request_count = render_request_count_;
        render_requested_ = true;
    }

    bool should_render() const {
        return render_requested_ || !first_frame_reported_ || cloth_preview_active();
    }

    std::string capture_back_buffer_to_png(const fs::path& output) {
        if (!device_ || !context_ || !swap_chain_) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"D3D11 device is not ready\"}";
        }
        if (output.empty()) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"capture path is empty\"}";
        }
        try {
            if (output.has_parent_path()) {
                fs::create_directories(output.parent_path());
            }
        } catch (const std::exception& exc) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"create_directories failed: "
                << json_escape(exc.what()) << "\"}";
            return out.str();
        }
        ComPtr<ID3D11Texture2D> back_buffer;
        HRESULT hr = swap_chain_->GetBuffer(0, IID_PPV_ARGS(back_buffer.GetAddressOf()));
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"GetBuffer failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        DirectX::ScratchImage image;
        hr = DirectX::CaptureTexture(device_.Get(), context_.Get(), back_buffer.Get(), image);
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"CaptureTexture failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        const DirectX::Image* frame = image.GetImage(0, 0, 0);
        if (frame == nullptr) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"CaptureTexture returned no image\"}";
        }
        hr = DirectX::SaveToWICFile(*frame, DirectX::WIC_FLAGS_NONE, GUID_ContainerFormatPng, output.c_str());
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"SaveToWICFile failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        std::ostringstream out;
        out << "{\"event\":\"frame_capture\",\"ok\":true,\"path\":\"" << json_escape(cdmw_native_diag::path_to_utf8(output)) << "\"}";
        return out.str();
    }

    void note_render_suppressed(const char* reason) {
        ++render_suppressed_count_;
        stats_.render_suppressed_count = render_suppressed_count_;
        if (reason && reason[0]) {
            stats_.parent_health = reason;
            stats_.render_suppressed_reason = reason;
            stats_.parent_renderable = std::string(reason) != "parent_not_renderable";
        }
        if (render_suppressed_count_ == 1 || render_suppressed_count_ % 120 == 0) {
            cdmw_native_diag::event(
                "render_suppressed",
                {
                    {"reason", reason && reason[0] ? reason : "not_visible"},
                    {"render_suppressed_count", std::to_string(render_suppressed_count_)},
                    {"render_request_count", std::to_string(render_request_count_)},
                    {"frame_count", std::to_string(frame_count_)}
                });
        }
    }

    void set_parent_health(const std::string& health, std::uint64_t unresponsive_count) {
        parent_health_ = health.empty() ? "ok" : health;
        parent_unresponsive_count_ = unresponsive_count;
        stats_.parent_health = parent_health_;
        stats_.parent_unresponsive_count = parent_unresponsive_count_;
    }

    void prune_srv_cache_if_needed(const char* reason) {
        if (srv_cache_.size() <= kSrvCacheSoftMaxEntries && estimated_texture_bytes_ <= kSrvCacheSoftMaxBytes) return;
        const size_t released_srv_entries = srv_cache_.size();
        const size_t released_texture_info_entries = texture_info_cache_.size();
        const std::uint64_t released_texture_bytes = estimated_texture_bytes_;
        srv_cache_.clear();
        texture_info_cache_.clear();
        estimated_texture_bytes_ = 0;
        active_texture_bytes_ = active_bound_texture_bytes();
        ++texture_cache_releases_;
        cdmw_native_diag::event(
            "texture_cache_pruned",
            {
                {"reason", reason && reason[0] ? reason : "soft_cap"},
                {"released_texture_cache_entries", std::to_string(released_srv_entries)},
                {"released_texture_info_entries", std::to_string(released_texture_info_entries)},
                {"released_estimated_texture_bytes", std::to_string(released_texture_bytes)},
                {"live_texture_bytes", std::to_string(active_texture_bytes_)},
                {"texture_cache_releases", std::to_string(texture_cache_releases_)}
            });
    }

    void release_model_resources(const char* reason) {
        const std::string reason_text = reason && reason[0] ? reason : "release";
        const size_t released_batches = batches_.size();
        const bool release_texture_cache =
            reason_text == "shutdown"
            || reason_text == "destructor"
            || reason_text == "clear"
            || reason_text == "load-missing-package"
            || reason_text == "parent_unresponsive"
            || reason_text == "parent_window_gone";
        const size_t released_srv_entries = release_texture_cache ? srv_cache_.size() : 0;
        const size_t released_texture_info_entries = release_texture_cache ? texture_info_cache_.size() : 0;
        const std::uint64_t released_texture_bytes = release_texture_cache ? estimated_texture_bytes_ : 0;
        const std::uint64_t released_live_texture_bytes = active_bound_texture_bytes();

        if (context_) {
            ID3D11ShaderResourceView* null_srvs[kTotalSrvCount] = {};
            context_->PSSetShaderResources(0, kTotalSrvCount, null_srvs);
            ID3D11Buffer* null_vertex_buffer = nullptr;
            UINT stride = 0;
            UINT offset = 0;
            context_->IASetVertexBuffers(0, 1, &null_vertex_buffer, &stride, &offset);
            context_->Flush();
        }
        batches_.clear();
        ++model_generation_;
        invalidate_mesh_edit_caches();
        cloth_colliders_.clear();
        active_texture_bytes_ = 0;
        if (release_texture_cache) {
            srv_cache_.clear();
            texture_info_cache_.clear();
            estimated_texture_bytes_ = 0;
        }
        if (released_batches || released_srv_entries || released_texture_info_entries || released_texture_bytes) {
            ++texture_cache_releases_;
        }
        stats_ = RendererStats{};
        update_runtime_stats();
        cdmw_native_diag::event(
            "model_resources_released",
            {
                {"reason", reason_text},
                {"released_batches", std::to_string(released_batches)},
                {"released_texture_cache_entries", std::to_string(released_srv_entries)},
                {"released_texture_info_entries", std::to_string(released_texture_info_entries)},
                {"released_estimated_texture_bytes", std::to_string(released_texture_bytes)},
                {"released_live_texture_bytes", std::to_string(released_live_texture_bytes)},
                {"texture_cache_releases", std::to_string(texture_cache_releases_)}
            });
    }

    bool load_package(const fs::path& package_dir, const fs::path& status_file, bool reset_view_state) {
        if (package_dir.empty() || !fs::is_directory(package_dir)) {
            release_model_resources("load-missing-package");
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            write_status(status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", "package directory missing"}, {"package_dir", cdmw_native_diag::path_to_utf8(package_dir)}});
            return false;
        }
        args_.preview_package = package_dir;
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        cdmw_native_diag::event("package_load_start", {{"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}, {"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)}});
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"percent\":85,\"current\":85,\"total\":100,\"message\":\"Loading native D3D11 preview package...\"}");
        auto start = std::chrono::steady_clock::now();
        std::string manifest;
        RendererStats next_stats;
        std::vector<PreviewBatch> next_batches;
        std::vector<ClothCollider> next_cloth_colliders;
        SkeletonOverlayState next_skeleton_overlay;
        ViewSettings next_view_settings;
        RenderTuning next_render_tuning;
        std::string next_display_mode;
        try {
            manifest = read_text(args_.preview_package / L"manifest.json");
            next_batches = parse_manifest_batches(args_.preview_package, manifest, next_stats);
            next_skeleton_overlay = parse_skeleton_overlay_state(manifest, next_stats);
            next_cloth_colliders = parse_cloth_colliders(args_.preview_package, manifest);
            next_stats.cloth_collider_count = static_cast<int>(next_cloth_colliders.size());
            next_view_settings = parse_view_settings(manifest);
            next_render_tuning = parse_render_tuning(manifest);
            next_display_mode = parse_display_mode(manifest, display_mode_);
        } catch (const std::exception& exc) {
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            write_status(args_.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 manifest read/parse failed\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", std::string("manifest read/parse failed: ") + exc.what()}, {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}});
            return false;
        }
        std::vector<std::string> missing_paths;
        auto require_path = [&](const std::wstring& path, const char* label) {
            if (path.empty()) return;
            if (!fs::is_regular_file(fs::path(path)) && missing_paths.size() < 12) {
                missing_paths.push_back(std::string(label) + ":" + wide_to_utf8(path));
            }
        };
        for (const PreviewBatch& batch : next_batches) {
            require_path(batch.vertex_file, "vertex");
            require_path(batch.base_dds, "base_dds");
            require_path(batch.normal_dds, "normal_dds");
            require_path(batch.material_dds, "material_dds");
            require_path(batch.specular_dds, "specular_dds");
            require_path(batch.detail_dds, "detail_dds");
            require_path(batch.height_dds, "height_dds");
            require_path(batch.emissive_dds, "emissive_dds");
            require_path(batch.base_png, "base_png");
            require_path(batch.height_png, "height_png");
            require_path(batch.emissive_png, "emissive_png");
            if (batch.cloth.available) {
                require_path(batch.cloth.particle_file, "cloth_particles");
                require_path(batch.cloth.pin_file, "cloth_pins");
                require_path(batch.cloth.constraint_file, "cloth_constraints");
            }
            for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
                const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                require_path(layer.diffuse_dds, "layer_diffuse");
                require_path(layer.mask_dds, "layer_mask");
                require_path(layer.material_dds, "layer_material");
                require_path(layer.normal_dds, "layer_normal");
                require_path(layer.height_dds, "layer_height");
            }
        }
        if (next_batches.empty() || !missing_paths.empty()) {
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            std::ostringstream message;
            message << (next_batches.empty() ? "native D3D11 manifest had no renderable batches" : "native D3D11 manifest referenced missing files");
            write_status(args_.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 package validation failed\"}");
            cdmw_native_diag::event(
                "package_load_error",
                {
                    {"reason", message.str()},
                    {"missing_count", std::to_string(missing_paths.size())},
                    {"missing_examples", missing_paths.empty() ? "" : missing_paths.front()},
                    {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}
                });
            return false;
        }
        next_stats.manifest_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"percent\":90,\"current\":90,\"total\":100,\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
        if (!upload_batches(next_batches, next_stats)) {
            write_status(args_.status_file, error_payload("native D3D11 package reload failed", next_stats));
            cdmw_native_diag::event(
                "package_load_error",
                {
                    {"reason", "upload failed"},
                    {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)},
                    {"texture_failures", std::to_string(next_stats.texture_failures)},
                    {"skipped", std::to_string(next_stats.skipped.size())}
                });
            return false;
        }
        release_model_resources("reload");
        batches_ = std::move(next_batches);
        cloth_colliders_ = std::move(next_cloth_colliders);
        skeleton_overlay_ = std::move(next_skeleton_overlay);
        hidden_source_submeshes_.clear();
        stats_ = next_stats;
        if (!view_settings_overridden_) {
            view_settings_ = next_view_settings;
        }
        if (!render_tuning_overridden_) {
            render_tuning_ = next_render_tuning;
        }
        display_mode_ = normalize_display_mode(next_display_mode, display_mode_);
        first_frame_started_ = false;
        first_frame_reported_ = false;
        mesh_edit_.drag_active = false;
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.selection_lasso_points.clear();
        mesh_edit_.selected_vertices.clear();
        mesh_edit_.selected_edges.clear();
        mesh_edit_.selected_faces.clear();
        mesh_edit_.selected_sources.clear();
        hidden_source_submeshes_.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.origin_cache_valid = false;
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (reset_view_state) {
            reset_view();
        }
        update_runtime_stats();
        write_status(args_.status_file, resources_loaded_payload(stats_));
        request_render();
        cdmw_native_diag::event(
            "package_loaded",
            {
                {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)},
                {"batches", std::to_string(stats_.batch_count)},
                {"vertices", std::to_string(stats_.vertex_count)},
                {"display_mode", display_mode_},
                {"dds_uploaded_base", std::to_string(stats_.dds_uploaded.base)},
                {"png_fallback", std::to_string(stats_.png_fallback)},
                {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
            });
        return true;
    }

    bool clear_preview(const fs::path& status_file) {
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        release_model_resources("clear");
        skeleton_overlay_ = SkeletonOverlayState{};
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        first_frame_started_ = true;
        first_frame_reported_ = true;
        mesh_edit_.drag_active = false;
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.selection_lasso_points.clear();
        mesh_edit_.selected_vertices.clear();
        mesh_edit_.selected_edges.clear();
        mesh_edit_.selected_faces.clear();
        mesh_edit_.selected_sources.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.selected_source_submeshes.clear();
        alignment_.part_transforms.clear();
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.scale_total = DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f);
        alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.origin_cache_valid = false;
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (hwnd_) {
            InvalidateRect(hwnd_, nullptr, FALSE);
        }
        request_render();
        update_runtime_stats();
        write_status(args_.status_file, cleared_payload(stats_));
        cdmw_native_diag::event(
            "preview_cleared",
            {
                {"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)},
                {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
            });
        return true;
    }

    bool handle_window_message(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) {
        switch (msg) {
        case WM_COPYDATA:
            result = handle_copy_data(reinterpret_cast<COPYDATASTRUCT*>(lparam)) ? 1 : 0;
            request_render();
            return true;
        case WM_SIZE:
            request_render();
            return false;
        case WM_PAINT:
        {
            PAINTSTRUCT ps{};
            BeginPaint(hwnd_, &ps);
            EndPaint(hwnd_, &ps);
            request_render();
            result = 0;
            return true;
        }
        case kCdmwSetZoomMessage:
            set_zoom_factor(static_cast<float>(wparam) / 1000.0f);
            request_render();
            result = 0;
            return true;
        case kCdmwSetFitMessage:
            set_fit_to_view(wparam != 0);
            request_render();
            result = 0;
            return true;
        case kCdmwResetViewMessage:
            reset_view();
            request_render();
            result = 0;
            return true;
        case WM_LBUTTONDBLCLK:
        {
            if (mesh_edit_.enabled || source_part_.picking_enabled) {
                source_part_.click_pending = false;
                result = 0;
                return true;
            }
            const PreviewViewRole reset_role = input_view_role_at(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            reset_camera_for_role(reset_role);
            send_view_event("reset_role", reset_role);
            request_render();
            result = 0;
            return true;
        }
        case WM_LBUTTONDOWN:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (begin_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (begin_alignment_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            begin_source_part_click(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            if (source_part_.click_pending) {
                request_render();
                result = 0;
                return true;
            }
            if (begin_mesh_edit_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            [[fallthrough]];
        case WM_MBUTTONDOWN:
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return true;
        case WM_RBUTTONDOWN:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (request_source_part_context(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return true;
        case WM_MOUSEMOVE:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (update_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (update_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (update_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                request_render();
                result = 0;
                return true;
            }
            update_alignment_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_source_part_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_mouse_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return drag_mode_ != 0;
        case WM_LBUTTONUP:
            if (finish_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (finish_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (finish_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                request_render();
                result = 0;
                return true;
            }
            finish_source_part_click(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            [[fallthrough]];
        case WM_MBUTTONUP:
        case WM_RBUTTONUP:
            end_mouse_drag(msg);
            request_render();
            result = 0;
            return true;
        case WM_CONTEXTMENU:
            result = 0;
            return true;
        case WM_CANCELMODE:
        case WM_KILLFOCUS:
            cancel_mouse_interaction();
            request_render();
            result = 0;
            return false;
        case WM_CAPTURECHANGED:
            cancel_mouse_interaction(false);
            request_render();
            return false;
        case WM_MOUSEWHEEL:
        {
            POINT point{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
            ScreenToClient(hwnd_, &point);
            apply_wheel_delta(GET_WHEEL_DELTA_WPARAM(wparam), point.x, point.y);
            request_render();
            result = 0;
            return true;
        }
        default:
            return false;
        }
    }

    void render() {
        if (!context_ || !swap_chain_) return;
        if (!resize_if_needed()) {
            render_requested_ = false;
            return;
        }
        step_cloth_simulation();
        flush_pending_mesh_edit_vertex_uploads();
        if (!first_frame_started_) {
            first_frame_timer_ = std::chrono::steady_clock::now();
            first_frame_started_ = true;
        }
        float clear[4] = {clear_color_.x, clear_color_.y, clear_color_.z, 1.0f};
        context_->OMSetRenderTargets(1, render_target_.GetAddressOf(), depth_view_.Get());
        context_->ClearRenderTargetView(render_target_.Get(), clear);
        context_->ClearDepthStencilView(depth_view_.Get(), D3D11_CLEAR_DEPTH, 1.0f, 0);
        context_->IASetInputLayout(input_layout_.Get());
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        context_->PSSetSamplers(0, 1, sampler_.GetAddressOf());
        for (const PreviewRenderView& view : active_render_views()) {
            draw_render_view(view);
        }
        draw_side_by_side_splitter_overlay();
        std::string capture_event;
        if (!pending_capture_path_.empty()) {
            fs::path capture_path = pending_capture_path_;
            pending_capture_path_.clear();
            capture_event = capture_back_buffer_to_png(capture_path);
        }
        swap_chain_->Present(1, 0);
        ValidateRect(hwnd_, nullptr);
        if (!icon_capture_mode_) {
            draw_alignment_overlay_gdi();
        }
        if (!capture_event.empty()) {
            send_json_event(capture_event);
        }
        ++frame_count_;
        stats_.frame_count = frame_count_;
        render_requested_ = false;
        if (!first_frame_reported_) {
            stats_.first_frame_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - first_frame_timer_).count();
            update_runtime_stats();
            write_status(args_.status_file, loaded_payload(stats_));
            first_frame_reported_ = true;
            cdmw_native_diag::event(
                "first_frame",
                {
                    {"first_frame_ms", std::to_string(stats_.first_frame_ms)},
                    {"batches", std::to_string(stats_.batch_count)},
                    {"vertices", std::to_string(stats_.vertex_count)},
                    {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                    {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                    {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                    {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
                });
        }
    }

    bool process_pending_commands() {
        bool processed = process_pending_mesh_edit_vertex_update();
        if (pending_package_dir_.empty()) return processed;
        if (alignment_.drag_active || alignment_.rotation_drag_active) {
            drop_pending_package_reload("alignment_drag_active");
            request_render();
            return processed;
        }
        fs::path package_dir = pending_package_dir_;
        fs::path status_file = pending_status_file_;
        bool reset_view_state = pending_reset_view_;
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        const bool loaded = load_package(package_dir, status_file, reset_view_state);
        request_render();
        return processed || loaded;
    }

private:
    bool process_pending_mesh_edit_vertex_update() {
        if (pending_mesh_edit_vertices_payload_.empty() && pending_mesh_edit_vertices_file_.empty()) return false;
        std::string payload;
        bool payload_file = false;
        fs::path file_path;
        bool delete_after = false;
        if (!pending_mesh_edit_vertices_file_.empty()) {
            file_path = pending_mesh_edit_vertices_file_;
            delete_after = pending_mesh_edit_vertices_delete_after_;
            pending_mesh_edit_vertices_file_.clear();
            pending_mesh_edit_vertices_delete_after_ = false;
            payload_file = true;
            payload = read_text(file_path);
        } else {
            payload.swap(pending_mesh_edit_vertices_payload_);
        }
        const int changed_vertices = payload.empty() ? 0 : update_mesh_edit_vertices_from_payload(payload);
        if (delete_after && !file_path.empty()) {
            const std::wstring filename = file_path.filename().wstring();
            if (filename.rfind(L"cdmw_mesh_edit_vertices_", 0) == 0) {
                std::error_code ec;
                fs::remove(file_path, ec);
            }
        }
        request_render();
        std::ostringstream event;
        event << "{\"event\":\"mesh_edit_vertices_updated\",\"changed_vertices\":" << changed_vertices;
        if (payload_file) {
            event << ",\"payload_file\":true";
        }
        event << "}";
        send_json_event(event.str());
        return true;
    }

    void queue_mesh_edit_vertices_payload(const std::string& payload) {
        pending_mesh_edit_vertices_payload_ = payload;
        pending_mesh_edit_vertices_file_.clear();
        pending_mesh_edit_vertices_delete_after_ = false;
        request_render();
    }

    void queue_mesh_edit_vertices_file(const fs::path& payload_file, bool delete_after) {
        pending_mesh_edit_vertices_payload_.clear();
        pending_mesh_edit_vertices_file_ = payload_file;
        pending_mesh_edit_vertices_delete_after_ = delete_after;
        request_render();
    }

    bool batch_is_reference(const PreviewBatch& batch) const {
        std::string role = lower_copy(batch.editor_role);
        return role.find("original") != std::string::npos
            || role.find("reference") != std::string::npos
            || (!batch.editor_editable && batch.source_submesh_index < 0 && !role.empty());
    }

    bool has_reference_batches() const {
        for (const PreviewBatch& batch : batches_) {
            if (batch_is_reference(batch)) return true;
        }
        return false;
    }

    static D3D11_VIEWPORT viewport_rect(float x, float y, float width, float height) {
        D3D11_VIEWPORT viewport{};
        viewport.TopLeftX = std::max(0.0f, x);
        viewport.TopLeftY = std::max(0.0f, y);
        viewport.Width = std::max(1.0f, width);
        viewport.Height = std::max(1.0f, height);
        viewport.MinDepth = 0.0f;
        viewport.MaxDepth = 1.0f;
        return viewport;
    }

    D3D11_VIEWPORT full_viewport() const {
        return viewport_rect(0.0f, 0.0f, static_cast<float>(std::max<LONG>(1, width_)), static_cast<float>(std::max<LONG>(1, height_)));
    }

    float side_by_side_reference_width() const {
        return std::floor(static_cast<float>(width_) * std::clamp(side_by_side_split_ratio_, 0.18f, 0.82f));
    }

    D3D11_VIEWPORT replacement_editor_viewport() const {
        if (display_mode_ == "side_by_side" && has_reference_batches() && width_ > 4) {
            const float left_width = side_by_side_reference_width();
            return viewport_rect(left_width + 1.0f, 0.0f, static_cast<float>(width_) - left_width - 1.0f, static_cast<float>(height_));
        }
        return full_viewport();
    }

    std::vector<PreviewRenderView> active_render_views() const {
        std::vector<PreviewRenderView> views;
        const bool has_reference = has_reference_batches();
        if (display_mode_ == "side_by_side" && has_reference && width_ > 4) {
            const float left_width = side_by_side_reference_width();
            PreviewRenderView left;
            left.viewport = viewport_rect(0.0f, 0.0f, left_width, static_cast<float>(height_));
            left.role = PreviewViewRole::Reference;
            left.reference_tint_alpha = 0.0f;
            views.push_back(left);
            PreviewRenderView right;
            right.viewport = viewport_rect(left_width + 1.0f, 0.0f, static_cast<float>(width_) - left_width - 1.0f, static_cast<float>(height_));
            right.role = PreviewViewRole::Replacement;
            views.push_back(right);
            return views;
        }
        if (display_mode_ == "overlay" && has_reference) {
            PreviewRenderView reference_overlay;
            reference_overlay.viewport = full_viewport();
            reference_overlay.role = PreviewViewRole::Reference;
            reference_overlay.reference_tint_alpha = 0.0f;
            views.push_back(reference_overlay);
            PreviewRenderView replacement;
            replacement.viewport = full_viewport();
            replacement.role = PreviewViewRole::Replacement;
            views.push_back(replacement);
            return views;
        }
        if (display_mode_ == "original_only" && has_reference) {
            PreviewRenderView reference;
            reference.viewport = full_viewport();
            reference.role = PreviewViewRole::Reference;
            reference.reference_tint_alpha = 0.0f;
            views.push_back(reference);
            return views;
        }
        PreviewRenderView only;
        only.viewport = full_viewport();
        only.role = (display_mode_ == "replacement_only" && has_reference) ? PreviewViewRole::Replacement : PreviewViewRole::All;
        views.push_back(only);
        return views;
    }

    bool batch_visible_in_view(const PreviewBatch& batch, PreviewViewRole role) const {
        if (batch.source_submesh_index >= 0 && hidden_source_submeshes_.find(batch.source_submesh_index) != hidden_source_submeshes_.end()) {
            return false;
        }
        if (role == PreviewViewRole::All) return true;
        const bool reference = batch_is_reference(batch);
        if (role == PreviewViewRole::Reference) return reference;
        if (role == PreviewViewRole::Replacement) return !reference;
        return true;
    }

    bool side_by_side_workspace_active() const {
        return display_mode_ == "side_by_side" && has_reference_batches() && width_ > 4;
    }

    bool side_by_side_splitter_hit_test(int x, int /*y*/) const {
        return side_by_side_workspace_active()
            && std::abs(static_cast<float>(x) - side_by_side_reference_width()) <= 10.0f;
    }

    void set_side_by_side_split_from_x(int x) {
        if (width_ <= 4) return;
        side_by_side_split_ratio_ = std::clamp(static_cast<float>(x) / static_cast<float>(width_), 0.18f, 0.82f);
    }

    void set_side_by_side_split_ratio(float ratio) {
        side_by_side_split_ratio_ = std::clamp(ratio, 0.18f, 0.82f);
    }

    PreviewViewRole input_view_role_at(int x, int /*y*/) const {
        if (!side_by_side_workspace_active()) return PreviewViewRole::All;
        const float left_width = side_by_side_reference_width();
        return static_cast<float>(x) <= left_width ? PreviewViewRole::Reference : PreviewViewRole::Replacement;
    }

    const PreviewCameraState& reference_camera() const {
        return reference_camera_;
    }

    PreviewCameraState& reference_camera() {
        return reference_camera_;
    }

    PreviewCameraState replacement_camera() const {
        PreviewCameraState camera;
        camera.yaw = yaw_;
        camera.pitch = pitch_;
        camera.fit_to_view = fit_to_view_;
        camera.zoom_factor = zoom_factor_;
        camera.distance = distance_;
        camera.pan_x = pan_x_;
        camera.pan_y = pan_y_;
        camera.pan_z = pan_z_;
        return camera;
    }

    void set_replacement_camera(const PreviewCameraState& camera) {
        yaw_ = camera.yaw;
        pitch_ = camera.pitch;
        fit_to_view_ = camera.fit_to_view;
        zoom_factor_ = camera.zoom_factor;
        distance_ = camera.distance;
        pan_x_ = camera.pan_x;
        pan_y_ = camera.pan_y;
        pan_z_ = camera.pan_z;
    }

    PreviewCameraState camera_for_view_role(PreviewViewRole role) const {
        if (role == PreviewViewRole::Reference) {
            return reference_camera_;
        }
        return replacement_camera();
    }

    void set_camera_for_role(PreviewViewRole role, const PreviewCameraState& camera) {
        if (role == PreviewViewRole::Reference) {
            reference_camera_ = camera;
            return;
        }
        if (role == PreviewViewRole::All) {
            reference_camera_ = camera;
        }
        set_replacement_camera(camera);
    }

    DirectX::XMMATRIX world_matrix_for_camera(const PreviewCameraState& camera) const {
        return DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(camera.pitch),
                DirectX::XMConvertToRadians(camera.yaw),
                0.0f)
            * DirectX::XMMatrixTranslation(camera.pan_x, camera.pan_y, camera.pan_z);
    }

    DirectX::XMMATRIX world_matrix_for_view_role(PreviewViewRole role) const {
        return world_matrix_for_camera(camera_for_view_role(role));
    }

    float distance_for_view_role(PreviewViewRole role) const {
        return camera_for_view_role(role).distance;
    }

    DirectX::XMMATRIX view_projection_matrix_for_viewport(const D3D11_VIEWPORT& viewport, float distance) const {
        DirectX::XMMATRIX view = DirectX::XMMatrixLookAtLH(
            DirectX::XMVectorSet(0.0f, 0.0f, -distance, 1.0f),
            DirectX::XMVectorSet(0.0f, 0.0f, 0.0f, 1.0f),
            DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f));
        DirectX::XMMATRIX projection = DirectX::XMMatrixPerspectiveFovLH(
            DirectX::XMConvertToRadians(kVerticalFovDegrees),
            std::max(1.0f, viewport.Width) / std::max(1.0f, viewport.Height),
            0.05f,
            100.0f);
        return view * projection;
    }

    static bool alignment_transform_value_active(
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) {
        constexpr float kEpsilon = 1.0e-6f;
        return std::abs(translation.x) > kEpsilon
            || std::abs(translation.y) > kEpsilon
            || std::abs(translation.z) > kEpsilon
            || std::abs(rotation.x) > kEpsilon
            || std::abs(rotation.y) > kEpsilon
            || std::abs(rotation.z) > kEpsilon
            || std::abs(scale.x - 1.0f) > kEpsilon
            || std::abs(scale.y - 1.0f) > kEpsilon
            || std::abs(scale.z - 1.0f) > kEpsilon;
    }

    bool alignment_global_transform_active() const {
        return alignment_transform_value_active(
            alignment_.translation_total,
            alignment_.rotation_total,
            alignment_.scale_total);
    }

    bool alignment_part_transform_active(const AlignmentState::PartTransform& transform) const {
        return alignment_transform_value_active(transform.translation, transform.rotation, transform.scale);
    }

    bool alignment_preview_transform_active() const {
        if (alignment_global_transform_active()) return true;
        for (const auto& item : alignment_.part_transforms) {
            if (alignment_part_transform_active(item.second)) return true;
        }
        return false;
    }

    bool alignment_non_translation_transform_active() const {
        constexpr float kEpsilon = 1.0e-6f;
        return std::abs(alignment_.rotation_total.x) > kEpsilon
            || std::abs(alignment_.rotation_total.y) > kEpsilon
            || std::abs(alignment_.rotation_total.z) > kEpsilon
            || std::abs(alignment_.scale_total.x - 1.0f) > kEpsilon
            || std::abs(alignment_.scale_total.y - 1.0f) > kEpsilon
            || std::abs(alignment_.scale_total.z - 1.0f) > kEpsilon;
    }

    bool alignment_batch_editable(const PreviewBatch& batch) const {
        return !batch_is_reference(batch) && batch.editor_editable;
    }

    bool alignment_batch_active(const PreviewBatch& batch) const {
        if (!alignment_batch_editable(batch)) return false;
        return alignment_.selected_source_submeshes.empty()
            || alignment_.selected_source_submeshes.find(batch.source_submesh_index) != alignment_.selected_source_submeshes.end();
    }

    bool alignment_origin_for_batches(DirectX::XMFLOAT3& origin, const std::set<int>* source_filter) const {
        if (source_filter == nullptr && alignment_.origin_cache_valid) {
            origin = alignment_.origin_cache;
            return true;
        }
        bool found = false;
        float min_x = 0.0f;
        float min_y = 0.0f;
        float min_z = 0.0f;
        float max_x = 0.0f;
        float max_y = 0.0f;
        float max_z = 0.0f;
        for (const PreviewBatch& batch : batches_) {
            if (!alignment_batch_editable(batch)) continue;
            if (source_filter != nullptr && source_filter->find(batch.source_submesh_index) == source_filter->end()) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                if (!found) {
                    min_x = max_x = position.x;
                    min_y = max_y = position.y;
                    min_z = max_z = position.z;
                    found = true;
                    continue;
                }
                min_x = std::min(min_x, position.x);
                min_y = std::min(min_y, position.y);
                min_z = std::min(min_z, position.z);
                max_x = std::max(max_x, position.x);
                max_y = std::max(max_y, position.y);
                max_z = std::max(max_z, position.z);
            }
        }
        if (!found) return false;
        origin = DirectX::XMFLOAT3(
            (min_x + max_x) * 0.5f,
            (min_y + max_y) * 0.5f,
            (min_z + max_z) * 0.5f);
        if (source_filter == nullptr) {
            alignment_.origin_cache = origin;
            alignment_.origin_cache_valid = true;
        }
        return true;
    }

    bool alignment_handle_origin_base(DirectX::XMFLOAT3& origin) const {
        if (!alignment_.selected_source_submeshes.empty()) {
            return alignment_origin_for_batches(origin, &alignment_.selected_source_submeshes);
        }
        return alignment_origin_for_batches(origin, nullptr);
    }

    bool alignment_global_origin_base(DirectX::XMFLOAT3& origin) const {
        return alignment_origin_for_batches(origin, nullptr);
    }

    bool alignment_part_origin_base(int source_submesh_index, DirectX::XMFLOAT3& origin) const {
        std::set<int> source_filter;
        source_filter.insert(source_submesh_index);
        return alignment_origin_for_batches(origin, &source_filter);
    }

    static DirectX::XMMATRIX alignment_transform_matrix(
        const DirectX::XMFLOAT3& origin,
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) {
        return DirectX::XMMatrixTranslation(-origin.x, -origin.y, -origin.z)
            * DirectX::XMMatrixScaling(
                std::max(0.001f, scale.x),
                std::max(0.001f, scale.y),
                std::max(0.001f, scale.z))
            * DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(rotation.x),
                DirectX::XMConvertToRadians(rotation.y),
                DirectX::XMConvertToRadians(rotation.z))
            * DirectX::XMMatrixTranslation(origin.x, origin.y, origin.z)
            * DirectX::XMMatrixTranslation(
                translation.x,
                translation.y,
                translation.z);
    }

    DirectX::XMMATRIX alignment_preview_transform_for_batch(const PreviewBatch& batch) const {
        if (!alignment_batch_editable(batch)) {
            return DirectX::XMMatrixIdentity();
        }
        DirectX::XMMATRIX transform = DirectX::XMMatrixIdentity();
        if (alignment_global_transform_active()) {
            DirectX::XMFLOAT3 origin{};
            if (!alignment_global_origin_base(origin)) {
                origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                origin,
                alignment_.translation_total,
                alignment_.rotation_total,
                alignment_.scale_total);
        }
        auto part = alignment_.part_transforms.find(batch.source_submesh_index);
        if (part != alignment_.part_transforms.end() && alignment_part_transform_active(part->second)) {
            DirectX::XMFLOAT3 origin{};
            if (!alignment_part_origin_base(batch.source_submesh_index, origin)) {
                origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                origin,
                part->second.translation,
                part->second.rotation,
                part->second.scale)
                * transform;
        }
        return transform;
    }

    DirectX::XMFLOAT3 transformed_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR transformed = DirectX::XMVector3TransformCoord(source, alignment_preview_transform_for_batch(batch));
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, transformed);
        return output;
    }

    static void append_line_vertex(
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

    void draw_colored_lines(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) {
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

    void draw_colored_triangles(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) {
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

    void draw_workspace_grid(const DirectX::XMMATRIX& world_view_projection) {
        std::vector<float> vertices;
        vertices.reserve(23u * 4u * 41u);
        constexpr int kGridHalfSteps = 12;
        constexpr float kGridStep = 0.25f;
        constexpr float kMajorEvery = 4.0f;
        constexpr float grid_y = 0.0f;
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

    void draw_alignment_axes(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
        if (!alignment_.enabled || view.role == PreviewViewRole::Reference) return;
        (void)world_view_projection;
        auto axis_points = alignment_axis_points();
        if (axis_points.empty()) return;

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

    static DirectX::XMFLOAT3 transform_coord(const DirectX::XMFLOAT3& point, const DirectX::XMMATRIX& matrix) {
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, DirectX::XMVector3TransformCoord(DirectX::XMLoadFloat3(&point), matrix));
        return output;
    }

    static void append_debug_line(
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

    static void append_debug_cross(
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

    static void append_debug_aabb(
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

    void draw_cloth_debug_overlays(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
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

    void draw_skeleton_overlay(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) {
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

    void draw_preview_batch(
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
        constants.material_params = DirectX::XMFLOAT4(
            mesh_edit_flat ? 0.0f : batch.normal_strength,
            mesh_edit_flat ? 0.0f : batch.height_amount,
            0.0f,
            0.0f);
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
                0.0f);
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

    bool mesh_edit_overlay_active_for_view(const PreviewRenderView& view) const {
        return mesh_edit_.enabled
            && !icon_capture_mode_
            && view.role != PreviewViewRole::Reference
            && width_ > 0
            && height_ > 0;
    }

    bool mesh_edit_source_allowed(int source_submesh_index) const {
        return source_submesh_index >= 0
            && (mesh_edit_.source_submesh_indices.empty()
                || mesh_edit_.source_submesh_indices.find(source_submesh_index) != mesh_edit_.source_submesh_indices.end());
    }

    bool mesh_edit_batch_editable_in_view(const PreviewBatch& batch, const PreviewRenderView& view) const {
        return mesh_edit_overlay_active_for_view(view)
            && batch_visible_in_view(batch, view.role)
            && batch.editor_editable
            && !batch_is_reference(batch)
            && batch.source_submesh_index >= 0
            && mesh_edit_source_allowed(batch.source_submesh_index)
            && !batch.cpu_positions.empty();
    }

    static bool mesh_edit_preserve_materials_for_batch(const PreviewBatch& batch) {
        (void)batch;
        return false;
    }

    std::pair<int, int> mesh_edit_source_key(const PreviewBatch& batch, size_t vertex_index) const {
        const int source_submesh = vertex_index < batch.cpu_source_submeshes.size()
            ? batch.cpu_source_submeshes[vertex_index]
            : batch.source_submesh_index;
        const int source_vertex = vertex_index < batch.cpu_source_vertices.size()
            ? batch.cpu_source_vertices[vertex_index]
            : static_cast<int>(vertex_index);
        return std::pair<int, int>(source_submesh, source_vertex);
    }

    void rebuild_batch_source_vertex_lookup(PreviewBatch& batch) const {
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

    void rebuild_batch_source_face_vertex_lookup(PreviewBatch& batch) const {
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

    bool mesh_edit_source_vertex_selected(const PreviewBatch& batch, size_t vertex_index) const {
        const std::pair<int, int> key = mesh_edit_source_key(batch, vertex_index);
        return key.first >= 0
            && key.second >= 0
            && mesh_edit_.selected_vertices.find(key) != mesh_edit_.selected_vertices.end();
    }

    std::pair<int, int> mesh_edit_source_face_key(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const {
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

    bool mesh_edit_source_face_selected(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const {
        const std::pair<int, int> key = mesh_edit_source_face_key(batch, triangle_index, base_vertex_index);
        return key.first >= 0
            && key.second >= 0
            && mesh_edit_.selected_faces.find(key) != mesh_edit_.selected_faces.end();
    }

    bool mesh_edit_source_edge_selected(const std::pair<int, int>& left, const std::pair<int, int>& right) const {
        return left.first >= 0
            && right.first >= 0
            && left.first == right.first
            && left.second >= 0
            && right.second >= 0
            && left.second != right.second
            && mesh_edit_.selected_edges.find(mesh_edit_edge_key(left.first, left.second, right.second)) != mesh_edit_.selected_edges.end();
    }

    bool project_batch_position_for_view(
        const PreviewBatch& batch,
        const DirectX::XMFLOAT3& position,
        const PreviewRenderView& view,
        float& screen_x,
        float& screen_y,
        float* depth_z = nullptr
    ) const {
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

    std::string mesh_edit_screen_vertex_cache_key(const PreviewRenderView& view) const {
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

    void invalidate_mesh_edit_caches() const {
        ++mesh_edit_cache_generation_;
        mesh_edit_screen_vertex_cache_.valid = false;
        mesh_edit_screen_vertex_cache_.vertices.clear();
        mesh_edit_depth_mask_cache_.valid = false;
        mesh_edit_depth_mask_cache_.depths.clear();
    }

    bool mesh_edit_depth_filter_enabled() const {
        return lower_copy(mesh_edit_.selection_depth_mode) != "xray";
    }

    const std::vector<MeshEditScreenVertex>& mesh_edit_screen_vertices_for_view(const PreviewRenderView& view) const {
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

    static float edge_function(float ax, float ay, float bx, float by, float cx, float cy) {
        return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax);
    }

    const MeshEditDepthMaskCache& mesh_edit_depth_mask_for_view(const PreviewRenderView& view) const {
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

    bool mesh_edit_screen_vertex_visible_in_depth_mask(
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

    void draw_mesh_edit_vertex_dots_instanced(
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

    void draw_mesh_edit_overlay(const PreviewRenderView& view) {
        if (!mesh_edit_overlay_active_for_view(view)) return;

        std::vector<float> vertices;
        std::vector<float> screen_overlay_vertices;
        vertices.reserve(23u * 4096u);
        screen_overlay_vertices.reserve(23u * 512u);
        DirectX::XMMATRIX identity = DirectX::XMMatrixIdentity();
        constexpr size_t kMaxMeshEditOverlayTriangles = 70000u;
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
        auto add_triangle_depth = [&](ScreenPoint a, float az, ScreenPoint b, float bz, ScreenPoint c, float cz, float r, float g, float blue) {
            append_screen_vertex(a.x, a.y, az, r, g, blue);
            append_screen_vertex(b.x, b.y, bz, r, g, blue);
            append_screen_vertex(c.x, c.y, cz, r, g, blue);
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

        size_t overlay_triangle_count = 0;
        overlay_vertices = &vertices;
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
                const bool selected_triangle =
                    selected_face
                    || selected_edge
                    || selected_vertex_triangle;
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
        draw_colored_triangles(vertices, identity, xray_mode);
        draw_colored_triangles(screen_overlay_vertices, identity, true);
        draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, xray_mode);
    }

    void draw_highlight_bounds_overlay(const PreviewRenderView& view) {
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

    void draw_render_view(const PreviewRenderView& view) {
        context_->RSSetViewports(1, &view.viewport);
        context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
        context_->OMSetDepthStencilState(view.no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        const DirectX::XMMATRIX camera_world = world_matrix_for_view_role(view.role);
        const DirectX::XMMATRIX view_projection = view_projection_matrix_for_viewport(view.viewport, distance_for_view_role(view.role));
        const DirectX::XMMATRIX world_view_projection = camera_world * view_projection;
        if (!view.wireframe && !icon_capture_mode_ && !(display_mode_ == "overlay" && view.role == PreviewViewRole::Reference)) {
            draw_workspace_grid(world_view_projection);
        }
        context_->RSSetViewports(1, &view.viewport);
        context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
        context_->OMSetDepthStencilState(view.no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        for (PreviewBatch& batch : batches_) {
            if (!batch_visible_in_view(batch, view.role)) continue;
            context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && !batch.two_sided && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
            const bool reference = batch_is_reference(batch);
            DirectX::XMFLOAT4 tint(
                1.0f,
                0.72f,
                0.18f,
                icon_capture_mode_ ? 0.0f : std::clamp(batch.highlight_strength, 0.0f, 0.74f));
            if (reference) {
                tint = DirectX::XMFLOAT4(
                    batch.highlight_strength > 0.0f ? 1.0f : 0.36f,
                    batch.highlight_strength > 0.0f ? 0.82f : 0.58f,
                    batch.highlight_strength > 0.0f ? 0.04f : 1.0f,
                    icon_capture_mode_ ? 0.0f : std::max(view.reference_tint_alpha, std::clamp(batch.highlight_strength, 0.0f, 0.82f)));
            }
            const DirectX::XMMATRIX alignment_transform =
                view.role == PreviewViewRole::Reference ? DirectX::XMMatrixIdentity() : alignment_preview_transform_for_batch(batch);
            const DirectX::XMMATRIX batch_world = alignment_transform * camera_world;
            const bool mesh_edit_active = mesh_edit_batch_editable_in_view(batch, view);
            const bool mesh_edit_flat = mesh_edit_active && !mesh_edit_preserve_materials_for_batch(batch);
            draw_preview_batch(batch, batch_world * view_projection, batch_world, tint, mesh_edit_flat);
        }
        draw_highlight_bounds_overlay(view);
        draw_cloth_debug_overlays(view, world_view_projection);
        draw_skeleton_overlay(view, world_view_projection);
        draw_mesh_edit_overlay(view);
        if (!icon_capture_mode_) {
            draw_alignment_axes(view, world_view_projection);
        }
    }

    void draw_side_by_side_splitter_overlay() {
        if (icon_capture_mode_ || !side_by_side_workspace_active()) return;
        D3D11_VIEWPORT viewport = full_viewport();
        context_->RSSetViewports(1, &viewport);
        std::vector<float> vertices;
        vertices.reserve(23u * 18u);
        const float split_x = side_by_side_reference_width();
        const float view_width = static_cast<float>(std::max<LONG>(1, width_));
        const float view_height = static_cast<float>(std::max<LONG>(1, height_));
        auto append_screen_vertex = [&](float x, float y, float r, float g, float b) {
            const float clip_x = (x / view_width) * 2.0f - 1.0f;
            const float clip_y = 1.0f - (y / view_height) * 2.0f;
            append_line_vertex(vertices, clip_x, clip_y, 0.0f, r, g, b);
        };
        auto add_rect = [&](float left, float top, float right, float bottom, float r, float g, float b) {
            append_screen_vertex(left, top, r, g, b);
            append_screen_vertex(right, top, r, g, b);
            append_screen_vertex(right, bottom, r, g, b);
            append_screen_vertex(left, top, r, g, b);
            append_screen_vertex(right, bottom, r, g, b);
            append_screen_vertex(left, bottom, r, g, b);
        };
        add_rect(split_x - 3.0f, 0.0f, split_x + 3.0f, view_height, 0.06f, 0.08f, 0.10f);
        const bool active = side_by_side_split_drag_active_ || side_by_side_split_hover_;
        add_rect(
            split_x - 1.0f,
            0.0f,
            split_x + 1.0f,
            view_height,
            active ? 1.0f : 0.38f,
            active ? 0.48f : 0.52f,
            active ? 0.16f : 0.64f);
        const float handle_top = std::max(14.0f, view_height * 0.5f - 34.0f);
        const float handle_bottom = std::min(view_height - 14.0f, view_height * 0.5f + 34.0f);
        add_rect(
            split_x - 5.0f,
            handle_top,
            split_x + 5.0f,
            handle_bottom,
            active ? 0.95f : 0.22f,
            active ? 0.48f : 0.30f,
            active ? 0.16f : 0.38f);
        draw_colored_triangles(vertices, DirectX::XMMatrixIdentity(), true);
    }

    void update_runtime_stats(RendererStats& stats) {
        stats.texture_cache_entries = static_cast<int>(srv_cache_.size());
        stats.texture_cache_releases = texture_cache_releases_;
        active_texture_bytes_ = active_bound_texture_bytes();
        stats.texture_cache_bytes = estimated_texture_bytes_;
        stats.live_texture_bytes = active_texture_bytes_;
        stats.estimated_texture_bytes = estimated_texture_bytes_ + active_texture_bytes_;
        stats.frame_count = frame_count_;
        stats.render_request_count = render_request_count_;
        stats.render_suppressed_count = render_suppressed_count_;
        stats.parent_unresponsive_count = parent_unresponsive_count_;
        stats.parent_health = parent_health_;
        const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
        if (memory.ok) {
            stats.process_working_set_bytes = memory.working_set_bytes;
            stats.process_private_bytes = memory.private_bytes;
        }
    }

    void update_runtime_stats() {
        update_runtime_stats(stats_);
    }

    std::uint64_t active_bound_texture_bytes() const {
        std::uint64_t total = 0;
        for (const PreviewBatch& batch : batches_) {
            total += batch.live_texture_bytes;
        }
        return total;
    }

    static std::wstring texture_file_identity(const std::wstring& path) {
        std::error_code ec;
        const fs::path file_path(path);
        const std::uintmax_t size = fs::file_size(file_path, ec);
        const std::wstring size_text = ec ? L"size:unknown" : (L"size:" + std::to_wstring(static_cast<unsigned long long>(size)));
        ec.clear();
        const auto mtime = fs::last_write_time(file_path, ec);
        const std::wstring mtime_text = ec ? L"mtime:unknown" : (L"mtime:" + std::to_wstring(mtime.time_since_epoch().count()));
        return size_text + L"|" + mtime_text;
    }

    static std::wstring texture_cache_key(
        const std::wstring& path,
        bool dds,
        DirectX::CREATETEX_FLAGS create_flags) {
        return (dds ? L"dds|" : L"wic|")
            + std::to_wstring(static_cast<uint32_t>(create_flags))
            + L"|"
            + texture_file_identity(path)
            + L"|"
            + path;
    }

    static float current_display_scale(float distance) {
        return std::max(0.1f, kFitDistance / std::max(distance, 0.01f));
    }

    float world_units_per_pixel() const {
        return world_units_per_pixel_for_role(PreviewViewRole::Replacement);
    }

    float world_units_per_pixel_for_role(PreviewViewRole role) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        if (role == PreviewViewRole::Reference && side_by_side_workspace_active()) {
            viewport = viewport_rect(0.0f, 0.0f, std::floor(static_cast<float>(width_) * 0.5f), static_cast<float>(height_));
        }
        float viewport_height = std::max(1.0f, viewport.Height);
        float visible_height = 2.0f * std::max(distance_for_view_role(role), 0.1f) * std::tan(DirectX::XMConvertToRadians(kVerticalFovDegrees) * 0.5f);
        return visible_height / viewport_height;
    }

    DirectX::XMMATRIX current_world_matrix() const {
        return DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(pitch_),
                DirectX::XMConvertToRadians(yaw_),
                0.0f)
            * DirectX::XMMatrixTranslation(pan_x_, pan_y_, pan_z_);
    }

    DirectX::XMMATRIX current_view_projection_matrix() const {
        return view_projection_matrix_for_viewport(replacement_editor_viewport(), distance_);
    }

    DirectX::XMMATRIX current_mvp_matrix() const {
        return current_world_matrix() * current_view_projection_matrix();
    }

    bool project_position(const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(source, current_mvp_matrix());
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        screen_x = viewport.TopLeftX + (clip.x * 0.5f + 0.5f) * viewport.Width;
        screen_y = viewport.TopLeftY + (0.5f - clip.y * 0.5f) * viewport.Height;
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

    bool project_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(
            source,
            alignment_preview_transform_for_batch(batch) * current_mvp_matrix());
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        screen_x = viewport.TopLeftX + (clip.x * 0.5f + 0.5f) * viewport.Width;
        screen_y = viewport.TopLeftY + (0.5f - clip.y * 0.5f) * viewport.Height;
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

    bool alignment_handle_origin(DirectX::XMFLOAT3& origin) const {
        if (!alignment_handle_origin_base(origin)) return false;
        DirectX::XMMATRIX transform = DirectX::XMMatrixIdentity();
        if (alignment_global_transform_active()) {
            DirectX::XMFLOAT3 global_origin{};
            if (!alignment_global_origin_base(global_origin)) {
                global_origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                global_origin,
                alignment_.translation_total,
                alignment_.rotation_total,
                alignment_.scale_total);
        }
        if (alignment_.selected_source_submeshes.size() == 1u) {
            const int source_index = *alignment_.selected_source_submeshes.begin();
            auto part = alignment_.part_transforms.find(source_index);
            if (part != alignment_.part_transforms.end() && alignment_part_transform_active(part->second)) {
                DirectX::XMFLOAT3 part_origin{};
                if (!alignment_part_origin_base(source_index, part_origin)) {
                    part_origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
                }
                transform = alignment_transform_matrix(
                    part_origin,
                    part->second.translation,
                    part->second.rotation,
                    part->second.scale)
                    * transform;
            }
        }
        DirectX::XMStoreFloat3(
            &origin,
            DirectX::XMVector3TransformCoord(DirectX::XMLoadFloat3(&origin), transform));
        return true;
    }

    std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> alignment_axis_points() const {
        std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> points;
        if (!alignment_.enabled || batches_.empty()) return points;
        DirectX::XMFLOAT3 origin{};
        if (!alignment_handle_origin(origin)) return points;
        float origin_x = 0.0f;
        float origin_y = 0.0f;
        if (!project_position(origin, origin_x, origin_y)) return points;
        const std::pair<const char*, DirectX::XMFLOAT3> axes[] = {
            {"x", DirectX::XMFLOAT3(origin.x + kAlignmentAxisExtent, origin.y, origin.z)},
            {"y", DirectX::XMFLOAT3(origin.x, origin.y + kAlignmentAxisExtent, origin.z)},
            {"z", DirectX::XMFLOAT3(origin.x, origin.y, origin.z + kAlignmentAxisExtent)},
        };
        for (const auto& axis : axes) {
            float end_x = 0.0f;
            float end_y = 0.0f;
            if (!project_position(axis.second, end_x, end_y)) continue;
            points[axis.first] = std::pair<ScreenPoint, ScreenPoint>(
                ScreenPoint{origin_x, origin_y},
                ScreenPoint{end_x, end_y});
        }
        return points;
    }

    static float distance_to_segment(float x, float y, const ScreenPoint& start, const ScreenPoint& end) {
        float vx = end.x - start.x;
        float vy = end.y - start.y;
        float length_sq = vx * vx + vy * vy;
        if (length_sq <= 1e-8f) {
            return std::hypot(x - start.x, y - start.y);
        }
        float t = std::clamp(((x - start.x) * vx + (y - start.y) * vy) / length_sq, 0.0f, 1.0f);
        float closest_x = start.x + vx * t;
        float closest_y = start.y + vy * t;
        return std::hypot(x - closest_x, y - closest_y);
    }

    std::string alignment_axis_at(int x, int y) const {
        if (!alignment_.enabled) return "";
        float center_distance = std::numeric_limits<float>::infinity();
        DirectX::XMFLOAT3 origin{};
        if (alignment_handle_origin(origin)) {
            float origin_x = 0.0f;
            float origin_y = 0.0f;
            if (project_position(origin, origin_x, origin_y)) {
                center_distance = std::hypot(static_cast<float>(x) - origin_x, static_cast<float>(y) - origin_y);
            }
        }
        std::string best_axis;
        float best_distance = 30.0f;
        for (const auto& [axis, segment] : alignment_axis_points()) {
            float distance = distance_to_segment(static_cast<float>(x), static_cast<float>(y), segment.first, segment.second);
            if (distance < best_distance) {
                best_axis = axis;
                best_distance = distance;
            }
        }
        if (!best_axis.empty() && (center_distance > 12.0f || best_distance + 4.0f < center_distance)) {
            return best_axis;
        }
        if (center_distance <= 26.0f) {
            return "screen";
        }
        return best_axis;
    }

    std::string alignment_rotation_handle_at(int x, int y) const {
        if (!alignment_.enabled) return "";
        DirectX::XMFLOAT3 origin{};
        if (!alignment_handle_origin(origin)) return "";
        float origin_x = 0.0f;
        float origin_y = 0.0f;
        if (!project_position(origin, origin_x, origin_y)) return "";
        const float distance = std::hypot(static_cast<float>(x) - origin_x, static_cast<float>(y) - origin_y);
        if (distance >= 34.0f && distance <= 58.0f) return "rotate";
        if (distance >= 62.0f && distance <= 84.0f) return "roll";
        return "";
    }

    DirectX::XMFLOAT3 alignment_screen_drag_delta(int delta_x, int delta_y, float units_per_pixel) const {
        DirectX::XMMATRIX rotation = DirectX::XMMatrixRotationRollPitchYaw(
            DirectX::XMConvertToRadians(pitch_),
            DirectX::XMConvertToRadians(yaw_),
            0.0f);
        DirectX::XMVECTOR determinant{};
        DirectX::XMMATRIX inverse_rotation = DirectX::XMMatrixInverse(&determinant, rotation);
        DirectX::XMVECTOR right = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(1.0f, 0.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR up = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR horizontal = DirectX::XMVectorScale(right, static_cast<float>(delta_x) * units_per_pixel);
        DirectX::XMVECTOR vertical = DirectX::XMVectorScale(up, static_cast<float>(delta_y) * units_per_pixel);
        DirectX::XMVECTOR delta = DirectX::XMVectorSubtract(horizontal, vertical);
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, delta);
        return output;
    }

    void send_alignment_vector_event(const char* event_name, const DirectX::XMFLOAT3& value) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"x\":" << value.x
            << ",\"y\":" << value.y
            << ",\"z\":" << value.z
            << "}";
        send_json_event(out.str());
    }

    bool alignment_drag_change_due(std::chrono::steady_clock::time_point& last_sent) const {
        auto now = std::chrono::steady_clock::now();
        if (last_sent.time_since_epoch().count() == 0) {
            last_sent = now;
            return true;
        }
        if (std::chrono::duration<double, std::milli>(now - last_sent).count() < 50.0) {
            return false;
        }
        last_sent = now;
        return true;
    }

    void send_alignment_started_event(const char* mode, const char* axis) const {
        std::ostringstream out;
        out << "{\"event\":\"alignment_drag_started\""
            << ",\"mode\":\"" << json_escape(mode ? mode : "") << "\""
            << ",\"axis\":\"" << json_escape(axis ? axis : "") << "\""
            << "}";
        send_json_event(out.str());
    }

    void drop_pending_package_reload(const char* reason) {
        if (pending_package_dir_.empty()) return;
        cdmw_native_diag::event(
            "pending_package_reload_dropped",
            {
                {"reason", reason ? reason : ""},
                {"package_dir", cdmw_native_diag::path_to_utf8(fs::path(pending_package_dir_))}
            });
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
    }

    bool begin_alignment_drag(WPARAM wparam, int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled) return false;
        if (input_view_role_at(x, y) == PreviewViewRole::Reference && side_by_side_workspace_active()) {
            return false;
        }
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        if (alt_down) {
            drop_pending_package_reload("alignment_rotation_start");
            alignment_.rotation_drag_active = true;
            alignment_.rotation_drag_roll = shift_down;
            alignment_.part_rotation_drag_bases.clear();
            if (!alignment_.selected_source_submeshes.empty()) {
                for (int source_index : alignment_.selected_source_submeshes) {
                    alignment_.part_rotation_drag_bases[source_index] = alignment_.part_transforms[source_index].rotation;
                }
                alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            } else {
                alignment_.rotation_drag_base = alignment_.rotation_total;
            }
            alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            alignment_.last_rotation_change_sent = std::chrono::steady_clock::time_point{};
            alignment_.last_x = x;
            alignment_.last_y = y;
            SetCapture(hwnd_);
            send_alignment_started_event("rotation", alignment_.rotation_drag_roll ? "roll" : "orbit");
            return true;
        }
        std::string rotation_handle = alignment_rotation_handle_at(x, y);
        if (!rotation_handle.empty()) {
            drop_pending_package_reload("alignment_rotation_start");
            alignment_.rotation_drag_active = true;
            alignment_.rotation_drag_roll = rotation_handle == "roll" || shift_down;
            alignment_.part_rotation_drag_bases.clear();
            if (!alignment_.selected_source_submeshes.empty()) {
                for (int source_index : alignment_.selected_source_submeshes) {
                    alignment_.part_rotation_drag_bases[source_index] = alignment_.part_transforms[source_index].rotation;
                }
                alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            } else {
                alignment_.rotation_drag_base = alignment_.rotation_total;
            }
            alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            alignment_.last_rotation_change_sent = std::chrono::steady_clock::time_point{};
            alignment_.last_x = x;
            alignment_.last_y = y;
            SetCapture(hwnd_);
            send_alignment_started_event("rotation", alignment_.rotation_drag_roll ? "roll" : "orbit");
            return true;
        }
        std::string axis = alignment_axis_at(x, y);
        if (axis.empty()) return false;
        drop_pending_package_reload("alignment_translation_start");
        alignment_.drag_axis = axis;
        alignment_.hover_axis = axis;
        alignment_.drag_active = true;
        alignment_.part_translation_drag_bases.clear();
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                alignment_.part_translation_drag_bases[source_index] = alignment_.part_transforms[source_index].translation;
            }
            alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        } else {
            alignment_.translation_drag_base = alignment_.translation_total;
        }
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.last_translation_change_sent = std::chrono::steady_clock::time_point{};
        alignment_.last_x = x;
        alignment_.last_y = y;
        SetCapture(hwnd_);
        send_alignment_started_event("translation", axis.c_str());
        return true;
    }

    bool update_alignment_translation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.drag_active || alignment_.drag_axis.empty()) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float movement_scale = shift_down ? 0.10f : (ctrl_down ? 4.0f : 1.0f);
        float units_per_pixel = world_units_per_pixel() * std::max(0.01f, alignment_.translation_sensitivity) * movement_scale;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.drag_axis == "screen") {
            delta = alignment_screen_drag_delta(delta_x, delta_y, units_per_pixel);
        } else {
            auto points = alignment_axis_points();
            auto found = points.find(alignment_.drag_axis);
            if (found == points.end()) return true;
            float axis_dx = found->second.second.x - found->second.first.x;
            float axis_dy = found->second.second.y - found->second.first.y;
            float axis_length = std::max(std::hypot(axis_dx, axis_dy), 1.0f);
            float projected_pixels = (static_cast<float>(delta_x) * axis_dx + static_cast<float>(delta_y) * axis_dy) / axis_length;
            float movement = projected_pixels * units_per_pixel;
            if (alignment_.drag_axis == "x") delta.x = movement;
            else if (alignment_.drag_axis == "y") delta.y = movement;
            else if (alignment_.drag_axis == "z") delta.z = movement;
        }
        alignment_.translation_drag_delta.x += delta.x;
        alignment_.translation_drag_delta.y += delta.y;
        alignment_.translation_drag_delta.z += delta.z;
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                DirectX::XMFLOAT3 base = alignment_.part_translation_drag_bases[source_index];
                alignment_.part_transforms[source_index].translation = DirectX::XMFLOAT3(
                    base.x + alignment_.translation_drag_delta.x,
                    base.y + alignment_.translation_drag_delta.y,
                    base.z + alignment_.translation_drag_delta.z);
            }
        } else {
            alignment_.translation_total = DirectX::XMFLOAT3(
                alignment_.translation_drag_base.x + alignment_.translation_drag_delta.x,
                alignment_.translation_drag_base.y + alignment_.translation_drag_delta.y,
                alignment_.translation_drag_base.z + alignment_.translation_drag_delta.z);
        }
        alignment_.origin_cache_valid = false;
        if (alignment_drag_change_due(alignment_.last_translation_change_sent)) {
            send_alignment_vector_event("alignment_drag_changed", alignment_.translation_drag_delta);
        }
        return true;
    }

    bool update_alignment_rotation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.rotation_drag_active) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float degrees_per_pixel = std::max(0.001f, alignment_.rotation_degrees_per_pixel);
        if (ctrl_down) degrees_per_pixel *= 4.0f;
        else if (shift_down && !alignment_.rotation_drag_roll) degrees_per_pixel *= 0.25f;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.rotation_drag_roll) {
            delta.z = static_cast<float>(delta_x) * degrees_per_pixel;
        } else {
            delta.x = static_cast<float>(delta_y) * degrees_per_pixel;
            delta.y = static_cast<float>(delta_x) * degrees_per_pixel;
        }
        alignment_.rotation_drag_delta.x += delta.x;
        alignment_.rotation_drag_delta.y += delta.y;
        alignment_.rotation_drag_delta.z += delta.z;
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                DirectX::XMFLOAT3 base = alignment_.part_rotation_drag_bases[source_index];
                alignment_.part_transforms[source_index].rotation = DirectX::XMFLOAT3(
                    base.x + alignment_.rotation_drag_delta.x,
                    base.y + alignment_.rotation_drag_delta.y,
                    base.z + alignment_.rotation_drag_delta.z);
            }
        } else {
            alignment_.rotation_total = DirectX::XMFLOAT3(
                alignment_.rotation_drag_base.x + alignment_.rotation_drag_delta.x,
                alignment_.rotation_drag_base.y + alignment_.rotation_drag_delta.y,
                alignment_.rotation_drag_base.z + alignment_.rotation_drag_delta.z);
        }
        alignment_.origin_cache_valid = false;
        if (alignment_drag_change_due(alignment_.last_rotation_change_sent)) {
            send_alignment_vector_event("alignment_rotation_changed", alignment_.rotation_drag_delta);
        }
        return true;
    }

    bool update_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) return update_alignment_rotation_drag(x, y, wparam);
        if (alignment_.drag_active) return update_alignment_translation_drag(x, y, wparam);
        return false;
    }

    void update_alignment_hover(int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled || alignment_.drag_active || alignment_.rotation_drag_active) {
            return;
        }
        std::string next_axis = alignment_rotation_handle_at(x, y);
        if (next_axis.empty()) {
            next_axis = alignment_axis_at(x, y);
        }
        if (next_axis != alignment_.hover_axis) {
            alignment_.hover_axis = next_axis;
            request_render();
        }
    }

    bool finish_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) {
            update_alignment_rotation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_rotation_finished", alignment_.rotation_drag_delta);
            alignment_.rotation_drag_active = false;
            alignment_.rotation_drag_roll = false;
            alignment_.part_rotation_drag_bases.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        if (alignment_.drag_active) {
            update_alignment_translation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_drag_finished", alignment_.translation_drag_delta);
            alignment_.drag_active = false;
            alignment_.drag_axis.clear();
            alignment_.part_translation_drag_bases.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        return false;
    }

    bool cancel_alignment_drag() {
        bool was_active = alignment_.drag_active || alignment_.rotation_drag_active;
        if (alignment_.drag_active) {
            if (!alignment_.part_translation_drag_bases.empty()) {
                for (const auto& item : alignment_.part_translation_drag_bases) {
                    alignment_.part_transforms[item.first].translation = item.second;
                }
            } else {
                alignment_.translation_total = alignment_.translation_drag_base;
            }
        }
        if (alignment_.rotation_drag_active) {
            if (!alignment_.part_rotation_drag_bases.empty()) {
                for (const auto& item : alignment_.part_rotation_drag_bases) {
                    alignment_.part_transforms[item.first].rotation = item.second;
                }
            } else {
                alignment_.rotation_total = alignment_.rotation_drag_base;
            }
        }
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.rotation_drag_roll = false;
        alignment_.drag_axis.clear();
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.origin_cache_valid = false;
        return was_active;
    }

    void draw_alignment_overlay_gdi() const {
        // Text labels stay in the D3D frame so interaction remains stable.
        // The visible handles are rendered before Present.
    }

    int source_part_at(int x, int y, float radius_pixels) const {
        int best_source_submesh = -1;
        float best_distance = radius_pixels;
        for (const PreviewBatch& batch : batches_) {
            if (batch.source_submesh_index < 0 || batch.cpu_positions.empty()) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                if (!project_batch_position(batch, position, screen_x, screen_y)) continue;
                float distance = std::hypot(static_cast<float>(x) - screen_x, static_cast<float>(y) - screen_y);
                if (distance < best_distance) {
                    best_distance = distance;
                    best_source_submesh = batch.source_submesh_index;
                }
            }
        }
        return best_source_submesh;
    }

    void send_source_part_event(const char* event_name, int source_submesh_index) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"source_submesh_index\":" << source_submesh_index
            << "}";
        send_json_event(out.str());
    }

    void send_source_part_context_event(int source_submesh_index, int x, int y) const {
        std::ostringstream out;
        out << "{\"event\":\"source_part_context_requested\""
            << ",\"source_submesh_index\":" << source_submesh_index
            << ",\"x\":" << x
            << ",\"y\":" << y
            << "}";
        send_json_event(out.str());
    }

    void send_source_part_screen_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"toggle\""
            << ",\"target_mode\":\"source\""
            << ",\"selection_depth_mode\":\"xray\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, 28.0f, false)
            << ",\"falloff\":\"smooth\"}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

    void send_source_part_screen_context_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"context\""
            << ",\"target_mode\":\"source\""
            << ",\"selection_depth_mode\":\"xray\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, 28.0f, false)
            << ",\"falloff\":\"smooth\""
            << ",\"context_request\":true"
            << ",\"context_x\":" << x
            << ",\"context_y\":" << y
            << "}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

    void update_source_part_hover(int x, int y) {
        if (!source_part_.picking_enabled) {
            if (source_part_.hovered_source_submesh >= 0) {
                source_part_.hovered_source_submesh = -1;
                send_source_part_event("source_part_hovered", -1);
            }
            return;
        }
        if (mesh_edit_.enabled) {
            if (source_part_.hovered_source_submesh >= 0) {
                source_part_.hovered_source_submesh = -1;
                send_source_part_event("source_part_hovered", -1);
            }
            return;
        }
        int source_submesh = source_part_at(x, y, 28.0f);
        if (source_submesh == source_part_.hovered_source_submesh) return;
        source_part_.hovered_source_submesh = source_submesh;
        send_source_part_event("source_part_hovered", source_submesh);
    }

    void begin_source_part_click(WPARAM wparam, int x, int y) {
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (!source_part_.picking_enabled || alt_down || shift_down || ctrl_down) return;
        if (!mesh_edit_.enabled) {
            int source_submesh = source_part_at(x, y, 28.0f);
            if (source_submesh < 0) return;
            source_part_.click_source_submesh = source_submesh;
        }
        source_part_.click_pending = true;
        source_part_.start_x = x;
        source_part_.start_y = y;
    }

    void finish_source_part_click(int x, int y) {
        if (!source_part_.click_pending) return;
        int source_submesh = source_part_.click_source_submesh;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (std::hypot(static_cast<float>(x - source_part_.start_x), static_cast<float>(y - source_part_.start_y)) > 6.0f) {
            return;
        }
        if (mesh_edit_.enabled) {
            send_source_part_screen_selection_event(x, y);
            return;
        }
        if (source_submesh >= 0) {
            send_source_part_event("source_part_selected", source_submesh);
        }
    }

    bool request_source_part_context(WPARAM wparam, int x, int y) {
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (!source_part_.picking_enabled || alt_down || shift_down || ctrl_down) return false;
        if (mesh_edit_.enabled) {
            send_source_part_screen_context_event(x, y);
            return true;
        }
        int source_submesh = source_part_at(x, y, 28.0f);
        if (source_submesh < 0) return false;
        send_source_part_context_event(source_submesh, x, y);
        return true;
    }

    std::string mesh_edit_screen_drag_json(int start_x, int start_y, int end_x, int end_y) const {
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

    std::string mesh_edit_screen_radius_json(float radius_pixels) const {
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

    std::string mesh_edit_source_projection_overrides_json() const {
        if (!alignment_preview_transform_active()) {
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
            DirectX::XMStoreFloat4x4(&world_transform, alignment_preview_transform_for_batch(batch));
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

    std::string mesh_edit_screen_brush_json(int x, int y, float radius_pixels, bool include_source_filter = true) const {
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

    std::string mesh_edit_screen_region_json(int x, int y) const {
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

    std::string mesh_edit_payload_json(
        int x,
        int y,
        bool invert,
        bool include_screen_selection = false) const {
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

    void send_mesh_edit_event(const char* event_name, const std::string& payload_json) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\",\"payload\":" << payload_json << "}";
        send_json_event(out.str());
    }

    void add_mesh_edit_face_vertices_to_selection(int source_submesh, const std::set<int>& source_faces) {
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

    void add_mesh_edit_source_vertices_to_selection(int source_submesh) {
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

    static std::tuple<int, int, int> mesh_edit_edge_key(int source_submesh, int left, int right) {
        if (right < left) std::swap(left, right);
        return std::tuple<int, int, int>(source_submesh, left, right);
    }

    void send_mesh_edit_screen_brush_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"" << json_escape(mesh_edit_.selection_operation) << "\""
            << ",\"target_mode\":\"" << json_escape(mesh_edit_.target_mode) << "\""
            << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, mesh_edit_.radius_pixels)
            << ",\"falloff\":\"" << json_escape(mesh_edit_.falloff) << "\"}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

    void send_mesh_edit_screen_region_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"" << json_escape(mesh_edit_.selection_operation) << "\""
            << ",\"target_mode\":\"" << json_escape(mesh_edit_.target_mode) << "\""
            << ",\"selection_depth_mode\":\"" << json_escape(mesh_edit_.selection_depth_mode) << "\""
            << ",\"screen_region\":" << mesh_edit_screen_region_json(x, y) << "}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

    void send_mesh_edit_selection_event(bool include_screen_brush = false) {
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

    int update_mesh_edit_vertices_from_payload(const std::string& payload) {
        struct PositionUpdate {
            int source_vertex = -1;
            DirectX::XMFLOAT3 value;
        };
        struct NormalUpdate {
            int source_vertex = -1;
            DirectX::XMFLOAT3 value;
        };
        struct UvUpdate {
            int source_vertex = -1;
            DirectX::XMFLOAT2 value;
        };
        struct ParsedUpdateGroup {
            int source_submesh = -1;
            int source_vertex_start = 0;
            int source_vertex_count = 0;
            bool source_vertex_range = false;
            std::vector<PositionUpdate> positions;
            std::vector<NormalUpdate> normals;
            std::vector<UvUpdate> uvs;
        };
        std::vector<ParsedUpdateGroup> groups;
        std::set<int> group_source_submeshes;
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
        if (groups.empty()) return 0;
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
                        apply_position_update(static_cast<size_t>(update.source_vertex), update.value);
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
                    for (size_t vertex_index : lookup->second) {
                        apply_position_update(vertex_index, update.value);
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

    void flush_pending_mesh_edit_vertex_uploads() {
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

    std::pair<int, int> replace_mesh_edit_triangles_from_payload(const std::string& payload) {
        int replaced_batches = 0;
        int removed_batches = 0;
        const bool replace_all = json_bool_field(payload, "replace_all", false);
        const std::vector<std::string> groups = json_object_array_field(payload, "groups");
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
        if (replace_all) {
            const size_t before_count = batches_.size();
            batches_.erase(
                std::remove_if(
                    batches_.begin(),
                    batches_.end(),
                    [&](const PreviewBatch& batch) {
                        return batch.editor_editable
                            && !batch_is_reference(batch)
                            && batch.source_submesh_index >= 0
                            && requested_source_submeshes.find(batch.source_submesh_index) == requested_source_submeshes.end();
                    }),
                batches_.end());
            removed_batches = static_cast<int>(before_count - batches_.size());
            for (size_t index = 0; index < batches_.size(); ++index) {
                batches_[index].index = static_cast<int>(index);
            }
        } else if (!requested_source_submeshes.empty()) {
            const size_t before_count = batches_.size();
            batches_.erase(
                std::remove_if(
                    batches_.begin(),
                    batches_.end(),
                    [&](const PreviewBatch& batch) {
                        return batch.editor_editable
                            && !batch_is_reference(batch)
                            && batch.source_submesh_index >= 0
                            && requested_source_submeshes.find(batch.source_submesh_index) != requested_source_submeshes.end()
                            && group_source_submeshes.find(batch.source_submesh_index) == group_source_submeshes.end();
                    }),
                batches_.end());
            removed_batches = static_cast<int>(before_count - batches_.size());
            for (size_t index = 0; index < batches_.size(); ++index) {
                batches_[index].index = static_cast<int>(index);
            }
        }
        for (const std::string& group : groups) {
            const int source_submesh = static_cast<int>(json_float_field(group, "source_submesh_index", -1.0f));
            if (source_submesh < 0) continue;
            const std::vector<float> positions = json_f64_array_or_json_field(group, "positions_binary", "positions", 3);
            const std::vector<float> normals = json_f64_array_or_json_field(group, "normals_binary", "normals", 3);
            const std::vector<float> uvs = json_f64_array_or_json_field(group, "uvs_binary", "uvs", 2);
            const int source_vertex_start = json_int_field(group, "source_vertex_start", -1);
            const int source_vertex_range_count = json_int_field(group, "source_vertex_count", 0);
            const int source_face_start = json_int_field(group, "source_face_start", -1);
            const int source_face_range_count = json_int_field(group, "source_face_count", 0);
            const bool has_source_vertex_values =
                json_has_field(group, "source_vertex_indices_binary")
                || json_has_field(group, "source_vertex_indices");
            const bool has_source_face_values =
                json_has_field(group, "source_face_indices_binary")
                || json_has_field(group, "source_face_indices");
            const bool source_vertex_range =
                !has_source_vertex_values && source_vertex_start >= 0 && source_vertex_range_count > 0;
            const bool source_face_range =
                !has_source_face_values && source_face_start >= 0 && source_face_range_count > 0;
            std::vector<int> source_vertices;
            std::vector<int> source_faces;
            if (!source_vertex_range) {
                source_vertices = json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices");
            }
            if (!source_face_range) {
                source_faces = json_i32_array_or_json_field(group, "source_face_indices_binary", "source_face_indices");
            }
            const std::vector<int> indices = json_i32_array_or_json_field(group, "indices_binary", "indices");
            const bool indexed_payload = json_has_field(group, "indices") || json_has_field(group, "indices_binary");
            const std::string position_space = lower_copy(json_string_field(group, "position_space"));
            const bool source_space_positions = position_space == "source";
            const bool source_affine_positions = position_space == "source_affine";
            const std::vector<float> position_transform = json_float_array_field(group, "position_transform");
            const std::vector<float> normal_transform = json_float_array_field(group, "normal_transform");
            const std::vector<float> normalization_center = json_float_array_field(group, "normalization_center");
            float normalization_scale = json_float_field(group, "normalization_scale", 1.0f);
            if (!std::isfinite(normalization_scale) || std::abs(normalization_scale) <= 1e-8f) {
                normalization_scale = 1.0f;
            }
            const size_t source_vertex_count = positions.size() / 3u;
            auto source_vertex_id = [&](size_t source_slot) {
                if (source_vertex_range && source_slot < static_cast<size_t>(source_vertex_range_count)) {
                    return source_vertex_start + static_cast<int>(source_slot);
                }
                return source_slot < source_vertices.size() ? source_vertices[source_slot] : static_cast<int>(source_slot);
            };
            auto source_face_id = [&](size_t face_slot) {
                if (source_face_range && face_slot < static_cast<size_t>(source_face_range_count)) {
                    return source_face_start + static_cast<int>(face_slot);
                }
                return face_slot < source_faces.size() ? source_faces[face_slot] : static_cast<int>(face_slot);
            };
            int source_vertex_identity_count = static_cast<int>(source_vertex_count);
            if (source_vertex_range) {
                source_vertex_identity_count = std::max(source_vertex_identity_count, source_vertex_start + source_vertex_range_count);
            } else {
                for (const int source_vertex : source_vertices) {
                    source_vertex_identity_count = std::max(source_vertex_identity_count, source_vertex + 1);
                }
            }
            const size_t face_count = indexed_payload ? indices.size() / 3u : source_vertex_count / 3u;
            int source_face_identity_count = static_cast<int>(face_count);
            if (source_face_range) {
                source_face_identity_count = std::max(source_face_identity_count, source_face_start + source_face_range_count);
            } else {
                for (const int source_face : source_faces) {
                    source_face_identity_count = std::max(source_face_identity_count, source_face + 1);
                }
            }
            auto transform_replacement_position = [&](DirectX::XMFLOAT3 position) {
                if (source_affine_positions && position_transform.size() >= 12u) {
                    const float sx = position.x;
                    const float sy = position.y;
                    const float sz = position.z;
                    position.x = position_transform[0] * sx + position_transform[1] * sy + position_transform[2] * sz + position_transform[3];
                    position.y = position_transform[4] * sx + position_transform[5] * sy + position_transform[6] * sz + position_transform[7];
                    position.z = position_transform[8] * sx + position_transform[9] * sy + position_transform[10] * sz + position_transform[11];
                } else if (source_space_positions) {
                    const float cx = normalization_center.size() > 0u ? normalization_center[0] : 0.0f;
                    const float cy = normalization_center.size() > 1u ? normalization_center[1] : 0.0f;
                    const float cz = normalization_center.size() > 2u ? normalization_center[2] : 0.0f;
                    position.x = (position.x - cx) * normalization_scale;
                    position.y = (position.y - cy) * normalization_scale;
                    position.z = (position.z - cz) * normalization_scale;
                }
                return position;
            };
            auto transform_replacement_normal = [&](DirectX::XMFLOAT3 normal) {
                if (normal_transform.size() >= 9u) {
                    const float sx = normal.x;
                    const float sy = normal.y;
                    const float sz = normal.z;
                    normal.x = normal_transform[0] * sx + normal_transform[1] * sy + normal_transform[2] * sz;
                    normal.y = normal_transform[3] * sx + normal_transform[4] * sy + normal_transform[5] * sz;
                    normal.z = normal_transform[6] * sx + normal_transform[7] * sy + normal_transform[8] * sz;
                    const float length = std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
                    if (std::isfinite(length) && length > 1e-8f) {
                        normal.x /= length;
                        normal.y /= length;
                        normal.z /= length;
                    } else {
                        normal = DirectX::XMFLOAT3(0.0f, 1.0f, 0.0f);
                    }
                }
                return normal;
            };
            bool matched_batch = false;
            for (const PreviewBatch& batch : batches_) {
                if (batch.editor_editable && !batch_is_reference(batch) && batch.source_submesh_index == source_submesh) {
                    matched_batch = true;
                    break;
                }
            }
            if (!matched_batch && source_vertex_count > 0) {
                const int material_source_submesh = static_cast<int>(json_float_field(group, "material_source_submesh_index", source_submesh));
                const PreviewBatch* material_template = nullptr;
                for (const PreviewBatch& batch : batches_) {
                    if (batch.editor_editable && !batch_is_reference(batch) && batch.source_submesh_index == material_source_submesh) {
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
                new_batch.source_submesh_index = source_submesh;
                new_batch.source_local_submesh_index = source_submesh;
                new_batch.source_vertex_count = source_vertex_identity_count;
                new_batch.source_face_count = source_face_identity_count;
                new_batch.editor_role = "replacement_preview";
                new_batch.editor_editable = true;
                new_batch.part_label = json_string_field(group, "material_name", material_template ? material_template->part_label : "mesh_edit_part");
                new_batch.source_component_label = new_batch.part_label;
                const std::string alpha_mode = lower_copy(json_string_field(group, "preview_alpha_mode"));
                if (!alpha_mode.empty()) {
                    new_batch.alpha_cutout = alpha_mode == "mask" || alpha_mode == "alpha_cutout" || alpha_mode == "cutout";
                }
                new_batch.flip_v = json_bool_field(group, "preview_texture_flip_vertical", new_batch.flip_v);
                new_batch.two_sided = json_bool_field(group, "preview_double_sided", new_batch.two_sided);
                batches_.push_back(std::move(new_batch));
            }
            for (PreviewBatch& batch : batches_) {
                if (!batch.editor_editable || batch_is_reference(batch) || batch.source_submesh_index != source_submesh) continue;
                batch.source_vertex_count = source_vertex_identity_count;
                batch.source_face_count = source_face_identity_count;
                batch.cpu_positions.clear();
                batch.cpu_source_submeshes.clear();
                batch.cpu_source_vertices.clear();
                batch.cpu_source_faces.clear();
                batch.cpu_source_vertex_lookup.clear();
                batch.cpu_source_face_vertex_lookup.clear();
                batch.cpu_vertices.clear();
                batch.vertex_buffer.Reset();
                const size_t output_vertex_count = indexed_payload ? indices.size() : source_vertex_count;
                batch.cpu_positions.reserve(output_vertex_count);
                batch.cpu_source_submeshes.reserve(output_vertex_count);
                batch.cpu_source_vertices.reserve(output_vertex_count);
                batch.cpu_source_faces.reserve(output_vertex_count);
                batch.cpu_vertices.reserve(output_vertex_count * (kVertexStrideBytes / sizeof(float)));
                const float color_r = std::clamp(batch.base_color[0], 0.0f, 1.0f);
                const float color_g = std::clamp(batch.base_color[1], 0.0f, 1.0f);
                const float color_b = std::clamp(batch.base_color[2], 0.0f, 1.0f);
                auto append_vertex = [&](size_t source_slot, int source_face) {
                    if (source_slot >= source_vertex_count) return;
                    const DirectX::XMFLOAT3 position(
                        positions[source_slot * 3u],
                        positions[source_slot * 3u + 1u],
                        positions[source_slot * 3u + 2u]);
                    DirectX::XMFLOAT3 normal(0.0f, 1.0f, 0.0f);
                    if (normals.size() >= (source_slot + 1u) * 3u) {
                        normal = DirectX::XMFLOAT3(
                            normals[source_slot * 3u],
                            normals[source_slot * 3u + 1u],
                            normals[source_slot * 3u + 2u]);
                    }
                    const DirectX::XMFLOAT3 transformed_position = transform_replacement_position(position);
                    normal = transform_replacement_normal(normal);
                    DirectX::XMFLOAT2 uv(0.0f, 0.0f);
                    if (uvs.size() >= (source_slot + 1u) * 2u) {
                        uv = DirectX::XMFLOAT2(
                            uvs[source_slot * 2u],
                            uvs[source_slot * 2u + 1u]);
                    }
                    batch.cpu_positions.push_back(transformed_position);
                    batch.cpu_source_submeshes.push_back(source_submesh);
                    batch.cpu_source_vertices.push_back(source_vertex_id(source_slot));
                    batch.cpu_source_faces.push_back(source_face >= 0 ? source_face : static_cast<int>(source_slot / 3u));
                    const float values[23] = {
                        transformed_position.x, transformed_position.y, transformed_position.z,
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
                if (indexed_payload) {
                    for (size_t index_position = 0; index_position < indices.size(); ++index_position) {
                        const int raw_index = indices[index_position];
                        const size_t face_slot = index_position / 3u;
                        const int source_face = source_face_id(face_slot);
                        if (raw_index >= 0) append_vertex(static_cast<size_t>(raw_index), source_face);
                    }
                } else {
                    for (size_t index = 0; index < source_vertex_count; ++index) {
                        append_vertex(index, source_face_id(index / 3u));
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
        }
        if (replaced_batches > 0 || removed_batches > 0) {
            invalidate_mesh_edit_caches();
        }
        return std::pair<int, int>(replaced_batches, removed_batches);
    }

    static std::string mesh_edit_selection_operation_from_modifiers(WPARAM wparam) {
        const bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        const bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (shift_down && ctrl_down) return "toggle";
        if (ctrl_down) return "subtract";
        if (shift_down) return "add";
        return "replace";
    }

    void apply_mesh_edit_brush_selection(int x, int y) {
        send_mesh_edit_screen_brush_selection_event(x, y);
    }

    bool mesh_edit_preview_event_due(bool force_preview) const {
        if (force_preview || mesh_edit_.last_preview_event_time.time_since_epoch().count() == 0) return true;
        const auto now = std::chrono::steady_clock::now();
        const double elapsed_ms = std::chrono::duration<double, std::milli>(
            now - mesh_edit_.last_preview_event_time).count();
        return elapsed_ms >= 16.0;
    }

    void mark_mesh_edit_preview_event() {
        mesh_edit_.last_preview_event_time = std::chrono::steady_clock::now();
    }

    void apply_mesh_edit_region_selection(int x, int y) {
        send_mesh_edit_screen_region_selection_event(x, y);
    }

    void finish_mesh_edit_selection_drag(int x, int y) {
        apply_mesh_edit_region_selection(x, y);
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.selection_lasso_points.clear();
        if (GetCapture() == hwnd_) ReleaseCapture();
    }

    bool begin_mesh_edit_drag(WPARAM wparam, int x, int y) {
        if (!mesh_edit_.enabled) return false;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        if (alt_down) return false;
        bool remove_selection_mode = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode == "selection";
        bool selection_mode = mesh_edit_.tool == "vertex" || remove_selection_mode;
        if (selection_mode) {
            mesh_edit_.selection_drag_active = true;
            mesh_edit_.selection_operation = mesh_edit_selection_operation_from_modifiers(wparam);
            mesh_edit_.start_x = x;
            mesh_edit_.start_y = y;
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            mesh_edit_.selection_lasso_points.clear();
            if (mesh_edit_.selection_mode == "lasso") {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
            } else if (mesh_edit_.selection_mode == "brush") {
                apply_mesh_edit_brush_selection(x, y);
                if (mesh_edit_.selection_operation == "replace") {
                    mesh_edit_.selection_operation = "add";
                }
                mark_mesh_edit_preview_event();
            }
            SetCapture(hwnd_);
            return true;
        }
        const bool has_resident_selection = !mesh_edit_.selected_vertices.empty()
            || !mesh_edit_.selected_edges.empty()
            || !mesh_edit_.selected_faces.empty()
            || !mesh_edit_.selected_sources.empty();
        const bool selection_drag_tool = mesh_edit_.target_mode == "selection"
            && (mesh_edit_.tool == "move" || mesh_edit_.tool == "grab");
        bool move_screen_selection_tool = mesh_edit_.tool == "move" && !has_resident_selection;
        bool grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection;
        bool screen_selection_tool = move_screen_selection_tool || grab_screen_selection_tool;
        bool resident_selection_drag_tool = selection_drag_tool && has_resident_selection;
        bool remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection";
        bool screen_brush_tool = screen_selection_tool
            || remove_screen_tool
            || (mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection")
            || mesh_edit_.tool == "smooth"
            || mesh_edit_.tool == "inflate"
            || mesh_edit_.tool == "pinch";
        bool native_selection_tool = screen_brush_tool || resident_selection_drag_tool;
        if (!native_selection_tool) return true;
        mesh_edit_.drag_active = true;
        mesh_edit_.previewed = false;
        mesh_edit_.drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool;
        mesh_edit_.stroke_id += 1;
        mesh_edit_.start_x = x;
        mesh_edit_.start_y = y;
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.last_preview_event_time = std::chrono::steady_clock::time_point{};
        SetCapture(hwnd_);
        send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));
        return true;
    }

    bool update_mesh_edit_drag(int x, int y, bool force_preview = false) {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            if (mesh_edit_.selection_mode == "brush") {
                if (mesh_edit_preview_event_due(force_preview)) {
                    apply_mesh_edit_brush_selection(x, y);
                    mark_mesh_edit_preview_event();
                }
            } else if (mesh_edit_.selection_mode == "lasso") {
                if (mesh_edit_.selection_lasso_points.empty()
                    || std::hypot(
                        mesh_edit_.selection_lasso_points.back().x - static_cast<float>(x),
                        mesh_edit_.selection_lasso_points.back().y - static_cast<float>(y)) >= 2.0f) {
                    mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
                }
            }
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        if (!mesh_edit_preview_event_due(force_preview)) {
            return true;
        }
        bool drag_mode = mesh_edit_.tool == "move" || mesh_edit_.tool == "grab" || mesh_edit_.tool == "vertex";
        bool resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection;
        bool remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection";
        bool screen_brush_update_tool = remove_screen_tool
            || (mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection")
            || mesh_edit_.tool == "smooth"
            || mesh_edit_.tool == "inflate"
            || mesh_edit_.tool == "pinch";
        if (!screen_brush_update_tool && !resident_selection_drag) return true;
        bool ctrl_down = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.previewed = true;
        mark_mesh_edit_preview_event();
        return true;
    }

    bool finish_mesh_edit_drag(int x, int y) {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            if (mesh_edit_.selection_mode == "lasso") {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
            }
            if (mesh_edit_.selection_mode == "brush") {
                apply_mesh_edit_brush_selection(x, y);
                mark_mesh_edit_preview_event();
                mesh_edit_.selection_drag_active = false;
                mesh_edit_.selection_lasso_points.clear();
                if (GetCapture() == hwnd_) ReleaseCapture();
            } else {
                finish_mesh_edit_selection_drag(x, y);
            }
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        update_mesh_edit_drag(x, y, true);
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"finish\",\"tool\":\"" << json_escape(mesh_edit_.tool)
                << "\",\"delete_mode\":\"" << json_escape(mesh_edit_.delete_mode)
                << "\",\"previewed\":" << (mesh_edit_.previewed ? "true" : "false") << "}";
        send_mesh_edit_event("mesh_edit_stroke_finished", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

    bool cancel_mesh_edit_drag() {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.selection_drag_active = false;
            mesh_edit_.selection_lasso_points.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"cancel\",\"tool\":\"" << json_escape(mesh_edit_.tool)
                << "\",\"delete_mode\":\"" << json_escape(mesh_edit_.delete_mode) << "\"}";
        send_mesh_edit_event("mesh_edit_stroke_cancelled", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

    void send_json_event(const std::string& payload) const {
        HWND parent = reinterpret_cast<HWND>(args_.parent_hwnd);
        LRESULT delivered = 0;
        if (parent && IsWindow(parent)) {
            COPYDATASTRUCT cds{};
            cds.dwData = kCdmwEventCopyData;
            cds.cbData = static_cast<DWORD>(payload.size() + 1);
            cds.lpData = const_cast<char*>(payload.c_str());
            delivered = SendMessageW(parent, WM_COPYDATA, reinterpret_cast<WPARAM>(hwnd_), reinterpret_cast<LPARAM>(&cds));
        }
        if (!delivered) {
            write_status(args_.status_file, payload);
        }
    }

    void send_view_event(const char* reason, PreviewViewRole role = PreviewViewRole::Replacement) const {
        const PreviewCameraState camera = camera_for_view_role(role);
        std::ostringstream out;
        out << "{\"event\":\"view_state\",\"reason\":\"" << json_escape(reason ? reason : "") << "\""
            << ",\"role\":\"" << preview_view_role_name(role) << "\""
            << ",\"zoom_factor\":" << camera.zoom_factor
            << ",\"fit_to_view\":" << (camera.fit_to_view ? "true" : "false")
            << ",\"yaw\":" << camera.yaw
            << ",\"pitch\":" << camera.pitch
            << ",\"pan\":[" << camera.pan_x << "," << camera.pan_y << "," << camera.pan_z << "]"
            << "}";
        send_json_event(out.str());
    }

    void send_side_by_side_split_event(const char* reason) const {
        std::ostringstream out;
        out << "{\"event\":\"side_by_side_split\""
            << ",\"reason\":\"" << json_escape(reason ? reason : "") << "\""
            << ",\"ratio\":" << side_by_side_split_ratio_
            << "}";
        send_json_event(out.str());
    }

    bool handle_copy_data(const COPYDATASTRUCT* cds) {
        if (!cds || cds->dwData != kCdmwCommandCopyData || !cds->lpData || cds->cbData == 0) return false;
        const char* data = reinterpret_cast<const char*>(cds->lpData);
        size_t payload_size = static_cast<size_t>(cds->cbData);
        if (payload_size > 0 && data[payload_size - 1] == '\0') --payload_size;
        std::string payload(data, data + payload_size);
        std::string command = lower_copy(json_string_field(payload, "command"));
        if (command == "load_package") {
            pending_package_dir_ = utf8_to_wide(json_string_field(payload, "package_dir"));
            pending_status_file_ = utf8_to_wide(json_string_field(payload, "status_file"));
            pending_reset_view_ = json_bool_field(payload, "reset_view", false);
            if (json_has_field(payload, "side_by_side_split_ratio")) {
                set_side_by_side_split_ratio(json_float_field(payload, "side_by_side_split_ratio", side_by_side_split_ratio_));
            }
            request_render();
            cdmw_native_diag::event("command_load_package", {{"package_dir", cdmw_native_diag::path_to_utf8(fs::path(pending_package_dir_))}, {"status_file", cdmw_native_diag::path_to_utf8(fs::path(pending_status_file_))}});
            send_json_event("{\"event\":\"command_result\",\"command\":\"load_package\",\"ok\":true,\"queued\":true}");
            return true;
        }
        if (command == "clear_preview") {
            fs::path status_file = utf8_to_wide(json_string_field(payload, "status_file"));
            cdmw_native_diag::event("command_clear_preview", {{"status_file", cdmw_native_diag::path_to_utf8(status_file)}});
            clear_preview(status_file);
            send_json_event("{\"event\":\"command_result\",\"command\":\"clear_preview\",\"ok\":true}");
            return true;
        }
        if (command == "set_display_mode") {
            std::string mode = normalize_display_mode(json_string_field(payload, "mode", display_mode_), display_mode_);
            if (json_has_field(payload, "side_by_side_split_ratio")) {
                set_side_by_side_split_ratio(json_float_field(payload, "side_by_side_split_ratio", side_by_side_split_ratio_));
            }
            display_mode_ = mode;
            request_render();
            cdmw_native_diag::event("command_set_display_mode", {{"mode", display_mode_}});
            std::ostringstream event;
            event << "{\"event\":\"display_mode\",\"mode\":\"" << json_escape(display_mode_) << "\"}";
            send_json_event(event.str());
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return true;
        }
        if (command == "set_side_by_side_split") {
            set_side_by_side_split_ratio(json_float_field(payload, "ratio", side_by_side_split_ratio_));
            request_render();
            send_side_by_side_split_event("command");
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return true;
        }
        if (command == "set_render_tuning") {
            render_tuning_ = parse_render_tuning(payload);
            view_settings_ = parse_view_settings(payload);
            cloth_state_.enabled = json_bool_field(payload, "enable_tool_pbd_cloth_preview", cloth_state_.enabled);
            cloth_state_.paused = json_bool_field(payload, "pause_tool_pbd_cloth_preview", cloth_state_.paused);
            cloth_state_.show_pins = json_bool_field(payload, "show_tool_pbd_cloth_pins", cloth_state_.show_pins);
            cloth_state_.show_colliders = json_bool_field(payload, "show_tool_pbd_cloth_colliders", cloth_state_.show_colliders);
            cloth_state_.wind_strength = std::clamp(json_float_field(payload, "tool_pbd_cloth_wind_strength", cloth_state_.wind_strength), 0.0f, 2.0f);
            cloth_state_.wind_direction_degrees = std::clamp(json_float_field(payload, "tool_pbd_cloth_wind_direction_degrees", cloth_state_.wind_direction_degrees), -180.0f, 180.0f);
            if (json_bool_field(payload, "reset_tool_pbd_cloth_preview", false)) {
                reset_cloth_runtime();
            }
            render_tuning_overridden_ = true;
            view_settings_overridden_ = true;
            const bool sampler_ok = create_sampler_state();
            request_render();
            cdmw_native_diag::event(
                "command_set_render_tuning",
                {
                    {"max_anisotropy", std::to_string(render_tuning_.max_anisotropy)},
                    {"diagnostic_mode", std::to_string(render_tuning_.diagnostic_mode)},
                    {"d3d11_mip_lod_bias", std::to_string(render_tuning_.mip_lod_bias)},
                    {"d3d11_cull_back_faces", render_tuning_.cull_back_faces ? "true" : "false"},
                    {"d3d11_texture_address_mode", render_tuning_.texture_address_mode},
                    {"ambient_strength", std::to_string(render_tuning_.ambient_strength)},
                    {"diffuse_wrap_bias", std::to_string(render_tuning_.diffuse_wrap_bias)},
                    {"diffuse_light_scale", std::to_string(render_tuning_.diffuse_light_scale)},
                    {"specular_max", std::to_string(render_tuning_.specular_max)},
                    {"sampler_ok", sampler_ok ? "true" : "false"}
                });
            std::ostringstream event;
            event << "{\"event\":\"render_tuning\",\"ok\":" << (sampler_ok ? "true" : "false")
                  << ",\"max_anisotropy\":" << render_tuning_.max_anisotropy
                  << ",\"diagnostic_mode\":" << render_tuning_.diagnostic_mode
                  << ",\"d3d11_mip_lod_bias\":" << render_tuning_.mip_lod_bias
                  << ",\"d3d11_cull_back_faces\":" << (render_tuning_.cull_back_faces ? "true" : "false")
                  << ",\"d3d11_texture_address_mode\":\"" << json_escape(render_tuning_.texture_address_mode) << "\""
                  << ",\"ambient_strength\":" << render_tuning_.ambient_strength
                  << ",\"diffuse_wrap_bias\":" << render_tuning_.diffuse_wrap_bias
                  << ",\"diffuse_light_scale\":" << render_tuning_.diffuse_light_scale
                  << ",\"specular_max\":" << render_tuning_.specular_max
                  << ",\"sampler_max_anisotropy\":" << stats_.sampler_max_anisotropy
                  << ",\"sampler_mip_lod_bias\":" << stats_.sampler_mip_lod_bias
                  << ",\"sampler_recreate_count\":" << stats_.sampler_recreate_count
                  << ",\"cloth_enabled\":" << (cloth_state_.enabled ? "true" : "false")
                  << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "reset_tool_pbd_cloth_preview") {
            reset_cloth_runtime();
            request_render();
            send_json_event("{\"event\":\"cloth_preview_reset\",\"ok\":true}");
            return true;
        }
        if (command == "set_highlights") {
            std::set<int> highlighted;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                highlighted.insert(value);
            }
            std::set<int> highlighted_replacement;
            for (int value : json_int_array_field(payload, "replacement_submesh_indices")) {
                highlighted_replacement.insert(value);
            }
            std::set<int> highlighted_original;
            for (int value : json_int_array_field(payload, "original_submesh_indices")) {
                highlighted_original.insert(value);
            }
            const bool role_scoped = !highlighted_replacement.empty() || !highlighted_original.empty();
            int highlighted_batches = 0;
            for (PreviewBatch& batch : batches_) {
                std::string role = lower_copy(batch.editor_role);
                bool active = false;
                if (role_scoped && role == "original_reference") {
                    active = highlighted_original.find(batch.source_submesh_index) != highlighted_original.end();
                } else if (role_scoped && role == "replacement_preview") {
                    active = highlighted_replacement.find(batch.source_submesh_index) != highlighted_replacement.end();
                } else {
                    active = highlighted.find(batch.source_submesh_index) != highlighted.end();
                }
                batch.highlight_strength = active ? (role == "original_reference" ? 0.82f : 0.74f) : 0.0f;
                if (active) ++highlighted_batches;
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"highlight_state\",\"highlighted_batches\":" << highlighted_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_hidden_source_submeshes") {
            hidden_source_submeshes_.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) hidden_source_submeshes_.insert(value);
            }
            int visible_batches = 0;
            for (const PreviewBatch& batch : batches_) {
                if (batch.source_submesh_index < 0 || hidden_source_submeshes_.find(batch.source_submesh_index) == hidden_source_submeshes_.end()) {
                    ++visible_batches;
                }
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"part_visibility\",\"hidden_parts\":" << hidden_source_submeshes_.size()
                  << ",\"visible_batches\":" << visible_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_material_overrides") {
            const std::string requested_role = lower_copy(json_string_field(payload, "editor_role", "replacement_preview"));
            std::set<int> requested_sources;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) requested_sources.insert(value);
            }
            const bool scoped_sources = !requested_sources.empty();
            const bool has_brightness = json_has_field(payload, "texture_brightness");
            const bool has_roughness = json_has_field(payload, "roughness");
            const bool has_metalness = json_has_field(payload, "metalness");
            const bool has_specular = json_has_field(payload, "specular");
            const bool has_height_scale = json_has_field(payload, "height_scale");
            const bool has_emissive_intensity = json_has_field(payload, "emissive_intensity");
            const bool has_contrast = json_has_field(payload, "contrast");
            const bool has_saturation = json_has_field(payload, "saturation");
            const bool has_gamma = json_has_field(payload, "gamma");
            const std::vector<float> emissive_color = json_float_array_field(payload, "emissive_color");
            const std::vector<float> tint_color = json_float_array_field(payload, "tint_color");
            int updated_batches = 0;
            for (PreviewBatch& batch : batches_) {
                const std::string role = lower_copy(batch.editor_role);
                if (!requested_role.empty() && requested_role != "all" && role != requested_role) continue;
                if (scoped_sources && requested_sources.find(batch.source_submesh_index) == requested_sources.end()) continue;
                if (has_brightness) batch.texture_brightness = std::clamp(json_float_field(payload, "texture_brightness", batch.texture_brightness), 0.1f, 3.0f);
                if (has_roughness) batch.roughness_hint = std::clamp(json_float_field(payload, "roughness", batch.roughness_hint), 0.0f, 1.0f);
                if (has_metalness) batch.metalness_hint = std::clamp(json_float_field(payload, "metalness", batch.metalness_hint), 0.0f, 1.0f);
                if (has_specular) batch.specular_hint = std::clamp(json_float_field(payload, "specular", batch.specular_hint), 0.0f, 1.0f);
                if (has_height_scale) batch.height_scale_hint = std::clamp(json_float_field(payload, "height_scale", batch.height_scale_hint), 0.0f, 1.0f);
                if (has_emissive_intensity) batch.emissive_intensity = std::clamp(json_float_field(payload, "emissive_intensity", batch.emissive_intensity), 0.0f, 32.0f);
                if (has_contrast) batch.texture_contrast = std::clamp(json_float_field(payload, "contrast", batch.texture_contrast), 0.25f, 2.5f);
                if (has_saturation) batch.texture_saturation = std::clamp(json_float_field(payload, "saturation", batch.texture_saturation), 0.0f, 4.0f);
                if (has_gamma) batch.texture_gamma = std::clamp(json_float_field(payload, "gamma", batch.texture_gamma), 0.25f, 4.0f);
                if (emissive_color.size() >= 3) {
                    batch.emissive_color[0] = std::clamp(emissive_color[0], 0.0f, 2.0f);
                    batch.emissive_color[1] = std::clamp(emissive_color[1], 0.0f, 2.0f);
                    batch.emissive_color[2] = std::clamp(emissive_color[2], 0.0f, 2.0f);
                }
                if (tint_color.size() >= 3) {
                    batch.texture_tint[0] = std::clamp(tint_color[0], 0.0f, 4.0f);
                    batch.texture_tint[1] = std::clamp(tint_color[1], 0.0f, 4.0f);
                    batch.texture_tint[2] = std::clamp(tint_color[2], 0.0f, 4.0f);
                }
                ++updated_batches;
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"material_overrides\",\"updated_batches\":" << updated_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_texture_flip_vertical") {
            const bool enabled = json_bool_field(payload, "enabled", false);
            const std::string requested_role = lower_copy(json_string_field(payload, "editor_role", "replacement_preview"));
            std::set<int> source_filter;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) source_filter.insert(value);
            }
            int changed_batches = 0;
            int matched_batches = 0;
            for (PreviewBatch& batch : batches_) {
                const std::string role = lower_copy(batch.editor_role);
                if (!requested_role.empty() && requested_role != "all" && role != requested_role) {
                    continue;
                }
                if (!source_filter.empty() && source_filter.find(batch.source_submesh_index) == source_filter.end()) {
                    continue;
                }
                ++matched_batches;
                if (batch.flip_v != enabled) {
                    batch.flip_v = enabled;
                    ++changed_batches;
                }
            }
            if (changed_batches > 0) {
                request_render();
                if (hwnd_) {
                    InvalidateRect(hwnd_, nullptr, FALSE);
                }
            }
            std::ostringstream event;
            event << "{\"event\":\"texture_flip_vertical\",\"enabled\":" << (enabled ? "true" : "false")
                  << ",\"matched_batches\":" << matched_batches
                  << ",\"changed_batches\":" << changed_batches
                  << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_icon_capture_mode") {
            icon_capture_mode_ = json_bool_field(payload, "enabled", icon_capture_mode_);
            if (icon_capture_mode_) {
                alignment_.hover_axis.clear();
                alignment_.drag_axis.clear();
            }
            request_render();
            send_json_event("{\"event\":\"icon_capture_mode\",\"ok\":true}");
            return true;
        }
        if (command == "set_source_part_picking") {
            bool previous = source_part_.picking_enabled;
            source_part_.picking_enabled = json_bool_field(payload, "enabled", source_part_.picking_enabled);
            if (!source_part_.picking_enabled) {
                source_part_.click_pending = false;
                if (source_part_.hovered_source_submesh >= 0) {
                    source_part_.hovered_source_submesh = -1;
                    send_source_part_event("source_part_hovered", -1);
                }
            } else if (!previous) {
                source_part_.hovered_source_submesh = -1;
            }
            request_render();
            send_json_event("{\"event\":\"source_part_picking\",\"ok\":true}");
            return true;
        }
        if (command == "set_skeleton_overlay") {
            skeleton_overlay_.selected_bone_index = json_int_field(payload, "selected_bone_index", skeleton_overlay_.selected_bone_index);
            stats_.skeleton_selected_bone_index = skeleton_overlay_.selected_bone_index;
            request_render();
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            std::ostringstream event;
            event << "{\"event\":\"skeleton_overlay\",\"selected_bone_index\":" << skeleton_overlay_.selected_bone_index << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_mesh_edit_state") {
            mesh_edit_.enabled = json_bool_field(payload, "enabled", mesh_edit_.enabled);
            mesh_edit_.scope_mode = lower_copy(json_string_field(payload, "scope_mode", mesh_edit_.scope_mode));
            mesh_edit_.target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            mesh_edit_.tool = lower_copy(json_string_field(payload, "tool", mesh_edit_.tool));
            mesh_edit_.delete_mode = lower_copy(json_string_field(payload, "delete_mode", mesh_edit_.delete_mode));
            mesh_edit_.selection_mode = lower_copy(json_string_field(payload, "selection_mode", mesh_edit_.selection_mode));
            if (mesh_edit_.selection_mode != "brush" && mesh_edit_.selection_mode != "lasso" && mesh_edit_.selection_mode != "rectangle") {
                mesh_edit_.selection_mode = "brush";
            }
            mesh_edit_.selection_depth_mode = lower_copy(json_string_field(payload, "selection_depth_mode", mesh_edit_.selection_depth_mode));
            if (mesh_edit_.selection_depth_mode != "visible" && mesh_edit_.selection_depth_mode != "xray") {
                mesh_edit_.selection_depth_mode = "visible";
            }
            mesh_edit_.falloff = lower_copy(json_string_field(payload, "falloff", mesh_edit_.falloff));
            mesh_edit_.radius_pixels = std::clamp(json_float_field(payload, "radius_pixels", mesh_edit_.radius_pixels), 2.0f, 512.0f);
            mesh_edit_.strength = std::clamp(json_float_field(payload, "strength", mesh_edit_.strength), 0.0f, 1.0f);
            mesh_edit_.smooth_iterations = std::clamp(static_cast<int>(json_float_field(payload, "smooth_iterations", static_cast<float>(mesh_edit_.smooth_iterations))), 1, 12);
            mesh_edit_.show_vertices = json_bool_field(payload, "show_vertices", mesh_edit_.show_vertices);
            mesh_edit_.source_submesh_indices.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) mesh_edit_.source_submesh_indices.insert(value);
            }
            invalidate_mesh_edit_caches();
            if (!mesh_edit_.enabled) {
                cancel_mesh_edit_drag();
            }
            request_render();
            send_json_event("{\"event\":\"mesh_edit_state\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_state") {
            alignment_.enabled = json_bool_field(payload, "enabled", alignment_.enabled);
            alignment_.translation_sensitivity = std::clamp(
                json_float_field(payload, "translation_sensitivity", alignment_.translation_sensitivity),
                0.05f,
                10.0f);
            alignment_.rotation_degrees_per_pixel = std::clamp(
                json_float_field(payload, "rotation_degrees_per_pixel", alignment_.rotation_degrees_per_pixel),
                0.001f,
                8.0f);
            alignment_.selected_source_submeshes.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) alignment_.selected_source_submeshes.insert(value);
            }
            alignment_.origin_cache_valid = false;
            if (!alignment_.enabled) {
                cancel_alignment_drag();
                alignment_.hover_axis.clear();
            }
            request_render();
            send_json_event("{\"event\":\"alignment_state\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_transform") {
            alignment_.part_transforms.clear();
            alignment_.part_translation_drag_bases.clear();
            alignment_.part_rotation_drag_bases.clear();
            alignment_.translation_total = DirectX::XMFLOAT3(
                json_float_field(payload, "translation_x", alignment_.translation_total.x),
                json_float_field(payload, "translation_y", alignment_.translation_total.y),
                json_float_field(payload, "translation_z", alignment_.translation_total.z));
            alignment_.rotation_total = DirectX::XMFLOAT3(
                json_float_field(payload, "rotation_x", alignment_.rotation_total.x),
                json_float_field(payload, "rotation_y", alignment_.rotation_total.y),
                json_float_field(payload, "rotation_z", alignment_.rotation_total.z));
            alignment_.scale_total = DirectX::XMFLOAT3(
                std::clamp(json_float_field(payload, "scale_x", alignment_.scale_total.x), 0.001f, 1000.0f),
                std::clamp(json_float_field(payload, "scale_y", alignment_.scale_total.y), 0.001f, 1000.0f),
                std::clamp(json_float_field(payload, "scale_z", alignment_.scale_total.z), 0.001f, 1000.0f));
            request_render();
            send_json_event("{\"event\":\"alignment_transform\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_transforms") {
            auto triple = [](const std::string& object, const std::string& name, const DirectX::XMFLOAT3& fallback) {
                std::vector<float> values = json_float_array_field(object, name);
                if (values.size() < 3u) return fallback;
                return DirectX::XMFLOAT3(values[0], values[1], values[2]);
            };
            const std::string global = json_object_field(payload, "global");
            if (!global.empty()) {
                alignment_.translation_total = triple(global, "translation", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                alignment_.rotation_total = triple(global, "rotation_degrees", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                alignment_.scale_total = triple(global, "scale_xyz", DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f));
                alignment_.scale_total.x = std::clamp(alignment_.scale_total.x, 0.001f, 1000.0f);
                alignment_.scale_total.y = std::clamp(alignment_.scale_total.y, 0.001f, 1000.0f);
                alignment_.scale_total.z = std::clamp(alignment_.scale_total.z, 0.001f, 1000.0f);
            }
            alignment_.part_transforms.clear();
            for (const std::string& item : json_object_array_field(payload, "parts")) {
                AlignmentState::PartTransform transform;
                transform.translation = triple(item, "translation", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                transform.rotation = triple(item, "rotation_degrees", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                transform.scale = triple(item, "scale_xyz", DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f));
                transform.scale.x = std::clamp(transform.scale.x, 0.001f, 1000.0f);
                transform.scale.y = std::clamp(transform.scale.y, 0.001f, 1000.0f);
                transform.scale.z = std::clamp(transform.scale.z, 0.001f, 1000.0f);
                for (int source_index : json_int_array_field(item, "source_submesh_indices")) {
                    if (source_index >= 0) {
                        alignment_.part_transforms[source_index] = transform;
                    }
                }
            }
            alignment_.part_translation_drag_bases.clear();
            alignment_.part_rotation_drag_bases.clear();
            alignment_.origin_cache_valid = false;
            request_render();
            send_json_event("{\"event\":\"alignment_transforms\",\"ok\":true}");
            return true;
        }
        if (command == "clear_mesh_edit_selection") {
            mesh_edit_.selected_vertices.clear();
            mesh_edit_.selected_edges.clear();
            mesh_edit_.selected_faces.clear();
            mesh_edit_.selected_sources.clear();
            send_mesh_edit_selection_event();
            request_render();
            return true;
        }
        if (command == "set_mesh_edit_selection") {
            mesh_edit_.selected_vertices.clear();
            mesh_edit_.selected_edges.clear();
            mesh_edit_.selected_faces.clear();
            mesh_edit_.selected_sources.clear();
            for (const std::string& group : json_object_array_field(payload, "groups")) {
                int source_submesh = static_cast<int>(json_float_field(group, "source_submesh_index", -1.0f));
                if (source_submesh < 0) continue;
                if (json_bool_field(group, "source_selected", false)) {
                    mesh_edit_.selected_sources.insert(source_submesh);
                    add_mesh_edit_source_vertices_to_selection(source_submesh);
                }
                for (int source_vertex : json_i32_range_or_array_or_json_field(
                         group,
                         "source_vertex_indices_binary",
                         "source_vertex_indices",
                         "source_vertex_start",
                         "source_vertex_count")) {
                    if (source_vertex >= 0) {
                        mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, source_vertex));
                    }
                }
                const std::vector<int> source_edges = json_i32_array_or_json_values_field(group, "source_edges_binary", "source_edges");
                for (size_t index = 0; index + 1u < source_edges.size(); index += 2u) {
                    const int left = source_edges[index];
                    const int right = source_edges[index + 1u];
                    if (left >= 0) mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, left));
                    if (right >= 0) mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, right));
                    if (left >= 0 && right >= 0 && left != right) {
                        mesh_edit_.selected_edges.insert(mesh_edit_edge_key(source_submesh, left, right));
                    }
                }
                std::set<int> source_faces;
                for (int source_face : json_i32_range_or_array_or_json_field(
                         group,
                         "source_face_indices_binary",
                         "source_face_indices",
                         "source_face_start",
                         "source_face_count")) {
                    if (source_face >= 0) {
                        source_faces.insert(source_face);
                        mesh_edit_.selected_faces.insert(std::pair<int, int>(source_submesh, source_face));
                    }
                }
                add_mesh_edit_face_vertices_to_selection(source_submesh, source_faces);
            }
            send_mesh_edit_selection_event();
            request_render();
            return true;
        }
        if (command == "select_mesh_edit_brush") {
            const int brush_x = json_int_field(payload, "x", last_mouse_x_);
            const int brush_y = json_int_field(payload, "y", last_mouse_y_);
            last_mouse_x_ = brush_x;
            last_mouse_y_ = brush_y;
            const std::string target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            if (target_mode == "vertex" || target_mode == "edge" || target_mode == "face" || target_mode == "source") {
                mesh_edit_.target_mode = target_mode;
            }
            mesh_edit_.selection_mode = "brush";
            mesh_edit_.selection_operation = lower_copy(json_string_field(payload, "operation", "replace"));
            apply_mesh_edit_brush_selection(brush_x, brush_y);
            request_render();
            return true;
        }
        if (command == "select_mesh_edit_region") {
            const std::string target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            if (target_mode == "vertex" || target_mode == "edge" || target_mode == "face" || target_mode == "source") {
                mesh_edit_.target_mode = target_mode;
            }
            mesh_edit_.selection_mode = lower_copy(json_string_field(payload, "selection_mode", mesh_edit_.selection_mode));
            if (mesh_edit_.selection_mode != "rectangle" && mesh_edit_.selection_mode != "lasso") {
                mesh_edit_.selection_mode = "rectangle";
            }
            mesh_edit_.selection_operation = lower_copy(json_string_field(payload, "operation", "replace"));
            mesh_edit_.selection_depth_mode = lower_copy(json_string_field(payload, "selection_depth_mode", mesh_edit_.selection_depth_mode));
            if (mesh_edit_.selection_depth_mode != "visible" && mesh_edit_.selection_depth_mode != "xray") {
                mesh_edit_.selection_depth_mode = "visible";
            }
            mesh_edit_.start_x = json_int_field(payload, "start_x", last_mouse_x_);
            mesh_edit_.start_y = json_int_field(payload, "start_y", last_mouse_y_);
            const int end_x = json_int_field(payload, "end_x", json_int_field(payload, "x", mesh_edit_.start_x));
            const int end_y = json_int_field(payload, "end_y", json_int_field(payload, "y", mesh_edit_.start_y));
            mesh_edit_.last_x = end_x;
            mesh_edit_.last_y = end_y;
            mesh_edit_.selection_lasso_points.clear();
            const std::vector<float> points = json_float_array_field(payload, "points");
            for (size_t index = 0; index + 1u < points.size(); index += 2u) {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(points[index], points[index + 1u]));
            }
            apply_mesh_edit_region_selection(end_x, end_y);
            request_render();
            return true;
        }
        if (command == "update_mesh_edit_vertices") {
            queue_mesh_edit_vertices_payload(payload);
            return true;
        }
        if (command == "update_mesh_edit_vertices_file") {
            const fs::path payload_file = utf8_to_wide(json_string_field(payload, "payload_file"));
            const bool delete_after = json_bool_field(payload, "delete_after", true);
            queue_mesh_edit_vertices_file(payload_file, delete_after);
            return true;
        }
        if (command == "replace_mesh_edit_triangles") {
            const auto [replaced_batches, removed_batches] = replace_mesh_edit_triangles_from_payload(payload);
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"mesh_edit_triangles_replaced\",\"replaced_batches\":" << replaced_batches
                  << ",\"removed_batches\":" << removed_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "replace_mesh_edit_triangles_file") {
            const fs::path payload_file = utf8_to_wide(json_string_field(payload, "payload_file"));
            const bool delete_after = json_bool_field(payload, "delete_after", true);
            const std::string file_payload = payload_file.empty() ? std::string() : read_text(payload_file);
            const auto [replaced_batches, removed_batches] = file_payload.empty()
                ? std::pair<int, int>(0, 0)
                : replace_mesh_edit_triangles_from_payload(file_payload);
            if (delete_after && !payload_file.empty()) {
                const std::wstring filename = payload_file.filename().wstring();
                if (filename.rfind(L"cdmw_mesh_edit_triangles_", 0) == 0) {
                    std::error_code ec;
                    fs::remove(payload_file, ec);
                }
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"mesh_edit_triangles_replaced\",\"replaced_batches\":" << replaced_batches
                  << ",\"removed_batches\":" << removed_batches
                  << ",\"payload_file\":true}";
            send_json_event(event.str());
            return true;
        }
        if (command == "capture_frame") {
            const fs::path output = utf8_to_wide(json_string_field(payload, "path"));
            if (output.empty()) {
                send_json_event("{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"capture path is empty\"}");
                return false;
            }
            pending_capture_path_ = output;
            request_render();
            render();
            return true;
        }
        if (command == "get_status") {
            update_runtime_stats();
            send_json_event(loaded_payload_for_event(stats_, "status"));
            return true;
        }
        if (command == "set_view") {
            std::string role_name = lower_copy(json_string_field(payload, "role", "replacement"));
            PreviewViewRole role = PreviewViewRole::Replacement;
            if (role_name == "reference") {
                role = PreviewViewRole::Reference;
            } else if (role_name == "all") {
                role = PreviewViewRole::All;
            }
            PreviewCameraState camera = camera_for_view_role(role);
            camera.yaw = json_float_field(payload, "yaw", camera.yaw);
            camera.pitch = std::clamp(json_float_field(payload, "pitch", camera.pitch), -89.0f, 89.0f);
            camera.zoom_factor = std::clamp(json_float_field(payload, "zoom_factor", camera.zoom_factor), 0.1f, kMaxZoomFactor);
            camera.fit_to_view = json_bool_field(payload, "fit_to_view", camera.fit_to_view);
            camera.distance = camera.fit_to_view ? kFitDistance : kFitDistance / std::max(camera.zoom_factor, 0.1f);
            camera.pan_x = json_float_field(payload, "pan_x", camera.pan_x);
            camera.pan_y = json_float_field(payload, "pan_y", camera.pan_y);
            camera.pan_z = json_float_field(payload, "pan_z", camera.pan_z);
            set_camera_for_role(role, camera);
            send_view_event("set_view", role);
            request_render();
            return true;
        }
        send_json_event("{\"event\":\"warning\",\"message\":\"unknown D3D11 host command\"}");
        return false;
    }

    static void reset_camera(PreviewCameraState& camera) {
        camera = PreviewCameraState{};
    }

    void reset_replacement_camera() {
        PreviewCameraState camera;
        reset_camera(camera);
        set_replacement_camera(camera);
    }

    void reset_camera_for_role(PreviewViewRole role) {
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

    void reset_view() {
        reset_replacement_camera();
        reset_camera(reference_camera_);
        drag_mode_ = 0;
        drag_button_ = 0;
        if (GetCapture() == hwnd_) ReleaseCapture();
        send_view_event("reset", PreviewViewRole::All);
    }

    void cancel_mouse_interaction(bool release_capture = true) {
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

    void set_zoom_factor(float zoom_factor) {
        zoom_factor_ = std::clamp(zoom_factor, 0.1f, kMaxZoomFactor);
        fit_to_view_ = false;
        distance_ = kFitDistance / zoom_factor_;
        send_view_event("zoom", PreviewViewRole::Replacement);
    }

    void set_fit_to_view(bool fit_to_view) {
        fit_to_view_ = fit_to_view;
        distance_ = fit_to_view_ ? kFitDistance : kFitDistance / std::max(zoom_factor_, 0.1f);
        send_view_event("fit", PreviewViewRole::Replacement);
    }

    void begin_mouse_drag(UINT msg, WPARAM wparam, int x, int y) {
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

    bool begin_side_by_side_split_drag(int x, int y) {
        if (!side_by_side_splitter_hit_test(x, y)) return false;
        side_by_side_split_drag_active_ = true;
        side_by_side_split_hover_ = true;
        set_side_by_side_split_from_x(x);
        SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
        if (GetCapture() != hwnd_) SetCapture(hwnd_);
        return true;
    }

    bool update_side_by_side_split_drag(int x, int y) {
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

    void update_mouse_drag(int x, int y) {
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

    void end_mouse_drag(UINT msg) {
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

    bool finish_side_by_side_split_drag(int x, int y) {
        if (!side_by_side_split_drag_active_) return false;
        set_side_by_side_split_from_x(x);
        side_by_side_split_drag_active_ = false;
        side_by_side_split_hover_ = side_by_side_splitter_hit_test(x, y);
        if (GetCapture() == hwnd_) ReleaseCapture();
        if (side_by_side_split_hover_) SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
        send_side_by_side_split_event("drag");
        return true;
    }

    void apply_wheel_delta(int wheel_delta, int x, int y) {
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

    bool create_render_targets() {
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

    bool resize_if_needed() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        LONG next_width = std::max<LONG>(1, rect.right - rect.left);
        LONG next_height = std::max<LONG>(1, rect.bottom - rect.top);
        if (next_width == width_ && next_height == height_) {
            return true;
        }
        width_ = next_width;
        height_ = next_height;
        if (context_) {
            ID3D11RenderTargetView* null_target = nullptr;
            context_->OMSetRenderTargets(1, &null_target, nullptr);
        }
        render_target_.Reset();
        depth_view_.Reset();
        HRESULT hr = swap_chain_->ResizeBuffers(0, static_cast<UINT>(width_), static_cast<UINT>(height_), DXGI_FORMAT_UNKNOWN, 0);
        if (FAILED(hr)) {
            stats_.skipped.push_back("swap chain resize failed");
            return false;
        }
        return create_render_targets();
    }

    bool create_pipeline() {
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

    bool create_sampler_state() {
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

    static DirectX::XMFLOAT3 add3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return DirectX::XMFLOAT3(a.x + b.x, a.y + b.y, a.z + b.z);
    }

    static DirectX::XMFLOAT3 sub3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return DirectX::XMFLOAT3(a.x - b.x, a.y - b.y, a.z - b.z);
    }

    static DirectX::XMFLOAT3 mul3(const DirectX::XMFLOAT3& a, float scale) {
        return DirectX::XMFLOAT3(a.x * scale, a.y * scale, a.z * scale);
    }

    static float dot3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) {
        return a.x * b.x + a.y * b.y + a.z * b.z;
    }

    static float length3(const DirectX::XMFLOAT3& value) {
        return std::sqrt(std::max(0.0f, dot3(value, value)));
    }

    static DirectX::XMFLOAT3 normalize3(
        const DirectX::XMFLOAT3& value,
        const DirectX::XMFLOAT3& fallback = DirectX::XMFLOAT3(0.0f, 0.0f, 1.0f)) {
        float length = length3(value);
        if (length <= 1e-8f || !std::isfinite(length)) return fallback;
        return mul3(value, 1.0f / length);
    }

    bool load_cloth_runtime(PreviewBatch& batch, RendererStats& stats) {
        ClothRuntime& cloth = batch.cloth;
        cloth.initialized = false;
        if (!cloth.available) return false;
        std::vector<uint8_t> particle_data = read_binary(cloth.particle_file);
        std::vector<uint8_t> pin_data = read_binary(cloth.pin_file);
        std::vector<uint8_t> constraint_data = read_binary(cloth.constraint_file);
        const size_t particle_count = static_cast<size_t>(std::max(0, cloth.particle_count));
        if (particle_count == 0 || particle_data.size() < particle_count * sizeof(float) * 3u) {
            stats.skipped.push_back("cloth particles missing/truncated:" + std::to_string(batch.index));
            cloth.available = false;
            return false;
        }
        cloth.rest_positions.clear();
        cloth.positions.clear();
        cloth.previous_positions.clear();
        cloth.pin_weights.clear();
        cloth.constraints.clear();
        cloth.rest_positions.reserve(particle_count);
        const float* particles = reinterpret_cast<const float*>(particle_data.data());
        for (size_t index = 0; index < particle_count; ++index) {
            DirectX::XMFLOAT3 position(particles[index * 3u], particles[index * 3u + 1u], particles[index * 3u + 2u]);
            cloth.rest_positions.push_back(position);
            cloth.positions.push_back(position);
            cloth.previous_positions.push_back(position);
        }
        if (pin_data.size() >= particle_count * sizeof(float)) {
            const float* pins = reinterpret_cast<const float*>(pin_data.data());
            for (size_t index = 0; index < particle_count; ++index) {
                cloth.pin_weights.push_back(std::clamp(pins[index], 0.0f, 1.0f));
            }
        } else {
            cloth.pin_weights.assign(particle_count, 0.0f);
        }
        constexpr size_t kConstraintBytes = sizeof(int32_t) * 2u + sizeof(float) * 2u;
        const size_t constraint_count = constraint_data.size() / kConstraintBytes;
        cloth.constraints.reserve(constraint_count);
        for (size_t index = 0; index < constraint_count; ++index) {
            const uint8_t* ptr = constraint_data.data() + index * kConstraintBytes;
            const int32_t* ints = reinterpret_cast<const int32_t*>(ptr);
            const float* floats = reinterpret_cast<const float*>(ptr + sizeof(int32_t) * 2u);
            ClothConstraint constraint;
            constraint.a = static_cast<int>(ints[0]);
            constraint.b = static_cast<int>(ints[1]);
            constraint.rest_length = std::max(0.0f, floats[0]);
            constraint.stiffness = std::clamp(floats[1], 0.0f, 1.0f);
            if (
                constraint.a >= 0
                && constraint.b >= 0
                && static_cast<size_t>(constraint.a) < particle_count
                && static_cast<size_t>(constraint.b) < particle_count
                && constraint.a != constraint.b
            ) {
                cloth.constraints.push_back(constraint);
            }
        }
        cloth.constraint_count = static_cast<int>(cloth.constraints.size());
        cloth.initialized = true;
        return true;
    }

    bool cloth_preview_active() const {
        if (!cloth_state_.enabled || cloth_state_.paused) return false;
        for (const PreviewBatch& batch : batches_) {
            if (batch.cloth.initialized) return true;
        }
        return false;
    }

    static void collide_point_with_sphere(DirectX::XMFLOAT3& point, const DirectX::XMFLOAT3& center, float radius) {
        if (radius <= 0.0f) return;
        DirectX::XMFLOAT3 delta = sub3(point, center);
        float length = length3(delta);
        if (length >= radius || length <= 1e-8f) return;
        DirectX::XMFLOAT3 normal = length > 1e-8f ? mul3(delta, 1.0f / length) : DirectX::XMFLOAT3(0.0f, 1.0f, 0.0f);
        point = add3(center, mul3(normal, radius + 0.004f));
    }

    static void collide_point_with_capsule(DirectX::XMFLOAT3& point, const ClothCollider& collider) {
        DirectX::XMFLOAT3 segment = sub3(collider.b, collider.a);
        float denom = dot3(segment, segment);
        float t = denom > 1e-8f ? std::clamp(dot3(sub3(point, collider.a), segment) / denom, 0.0f, 1.0f) : 0.0f;
        collide_point_with_sphere(point, add3(collider.a, mul3(segment, t)), collider.radius);
    }

    static void collide_point_with_aabb(DirectX::XMFLOAT3& point, const ClothCollider& collider) {
        if (
            point.x < collider.a.x || point.x > collider.b.x
            || point.y < collider.a.y || point.y > collider.b.y
            || point.z < collider.a.z || point.z > collider.b.z
        ) {
            return;
        }
        float distances[6] = {
            point.x - collider.a.x,
            collider.b.x - point.x,
            point.y - collider.a.y,
            collider.b.y - point.y,
            point.z - collider.a.z,
            collider.b.z - point.z,
        };
        int best = 0;
        for (int index = 1; index < 6; ++index) {
            if (distances[index] < distances[best]) best = index;
        }
        constexpr float kMargin = 0.006f;
        if (best == 0) point.x = collider.a.x - kMargin;
        else if (best == 1) point.x = collider.b.x + kMargin;
        else if (best == 2) point.y = collider.a.y - kMargin;
        else if (best == 3) point.y = collider.b.y + kMargin;
        else if (best == 4) point.z = collider.a.z - kMargin;
        else point.z = collider.b.z + kMargin;
    }

    void collide_cloth_particle(DirectX::XMFLOAT3& point) const {
        for (const ClothCollider& collider : cloth_colliders_) {
            if (collider.type == 1) collide_point_with_sphere(point, collider.a, collider.radius);
            else if (collider.type == 2) collide_point_with_capsule(point, collider);
            else if (collider.type == 3) collide_point_with_aabb(point, collider);
        }
    }

    void solve_cloth_constraint(ClothRuntime& cloth, const ClothConstraint& constraint) {
        DirectX::XMFLOAT3& a = cloth.positions[static_cast<size_t>(constraint.a)];
        DirectX::XMFLOAT3& b = cloth.positions[static_cast<size_t>(constraint.b)];
        DirectX::XMFLOAT3 delta = sub3(b, a);
        float length = length3(delta);
        if (length <= 1e-8f) return;
        float pin_a = constraint.a < static_cast<int>(cloth.pin_weights.size()) ? cloth.pin_weights[static_cast<size_t>(constraint.a)] : 0.0f;
        float pin_b = constraint.b < static_cast<int>(cloth.pin_weights.size()) ? cloth.pin_weights[static_cast<size_t>(constraint.b)] : 0.0f;
        float inv_a = std::max(0.0f, 1.0f - pin_a);
        float inv_b = std::max(0.0f, 1.0f - pin_b);
        float inv_sum = inv_a + inv_b;
        if (inv_sum <= 1e-6f) return;
        DirectX::XMFLOAT3 correction = mul3(delta, ((length - constraint.rest_length) / length) * constraint.stiffness);
        a = add3(a, mul3(correction, inv_a / inv_sum));
        b = sub3(b, mul3(correction, inv_b / inv_sum));
    }

    static void pin_cloth_particles(ClothRuntime& cloth) {
        for (size_t index = 0; index < cloth.positions.size(); ++index) {
            float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
            if (pin <= 0.0f) continue;
            const DirectX::XMFLOAT3& rest = cloth.rest_positions[index];
            DirectX::XMFLOAT3& point = cloth.positions[index];
            point.x = point.x * (1.0f - pin) + rest.x * pin;
            point.y = point.y * (1.0f - pin) + rest.y * pin;
            point.z = point.z * (1.0f - pin) + rest.z * pin;
        }
    }

    DirectX::XMFLOAT3 cloth_root_translation_for_batch(const PreviewBatch& batch) const {
        DirectX::XMFLOAT3 root(pan_x_, pan_y_, pan_z_);
        if (alignment_batch_editable(batch)) {
            root.x += alignment_.translation_total.x;
            root.y += alignment_.translation_total.y;
            root.z += alignment_.translation_total.z;
            auto part = alignment_.part_transforms.find(batch.source_submesh_index);
            if (part != alignment_.part_transforms.end()) {
                root.x += part->second.translation.x;
                root.y += part->second.translation.y;
                root.z += part->second.translation.z;
            }
        }
        return root;
    }

    void apply_cloth_root_motion(PreviewBatch& batch) {
        ClothRuntime& cloth = batch.cloth;
        if (!cloth.initialized || cloth.positions.empty()) return;
        bool part_non_translation_active = false;
        auto part = alignment_.part_transforms.find(batch.source_submesh_index);
        if (part != alignment_.part_transforms.end()) {
            constexpr float kEpsilon = 1.0e-6f;
            part_non_translation_active =
                std::abs(part->second.rotation.x) > kEpsilon
                || std::abs(part->second.rotation.y) > kEpsilon
                || std::abs(part->second.rotation.z) > kEpsilon
                || std::abs(part->second.scale.x - 1.0f) > kEpsilon
                || std::abs(part->second.scale.y - 1.0f) > kEpsilon
                || std::abs(part->second.scale.z - 1.0f) > kEpsilon;
        }
        const bool non_translation_active =
            alignment_batch_editable(batch)
            && (alignment_non_translation_transform_active() || part_non_translation_active);
        const DirectX::XMFLOAT3 root = cloth_root_translation_for_batch(batch);
        if (non_translation_active && !cloth.non_translation_reanchored) {
            cloth.positions = cloth.rest_positions;
            cloth.previous_positions = cloth.rest_positions;
            cloth.root_motion_initialized = false;
            cloth.non_translation_reanchored = true;
            apply_cloth_to_batch_vertices(batch);
        } else if (!non_translation_active) {
            cloth.non_translation_reanchored = false;
        }
        if (!cloth.root_motion_initialized) {
            cloth.last_root_translation = root;
            cloth.root_motion_initialized = true;
            return;
        }
        const DirectX::XMFLOAT3 delta = sub3(root, cloth.last_root_translation);
        cloth.last_root_translation = root;
        if (length3(delta) <= 1.0e-7f) return;
        for (size_t index = 0; index < cloth.positions.size(); ++index) {
            const float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
            const DirectX::XMFLOAT3 local_delta = mul3(delta, -(1.0f - pin));
            cloth.positions[index] = add3(cloth.positions[index], local_delta);
            if (index < cloth.previous_positions.size()) {
                cloth.previous_positions[index] = add3(cloth.previous_positions[index], local_delta);
            }
        }
    }

    void apply_cloth_to_batch_vertices(PreviewBatch& batch) {
        ClothRuntime& cloth = batch.cloth;
        if (!cloth.initialized || batch.cpu_vertices.size() < static_cast<size_t>(batch.vertex_count) * 23u) return;
        for (int vertex_index = 0; vertex_index < batch.vertex_count; ++vertex_index) {
            int source_vertex = vertex_index < static_cast<int>(batch.cpu_source_vertices.size())
                ? batch.cpu_source_vertices[static_cast<size_t>(vertex_index)]
                : vertex_index;
            if (source_vertex < 0 || static_cast<size_t>(source_vertex) >= cloth.positions.size()) continue;
            const DirectX::XMFLOAT3& point = cloth.positions[static_cast<size_t>(source_vertex)];
            size_t offset = static_cast<size_t>(vertex_index) * 23u;
            batch.cpu_vertices[offset] = point.x;
            batch.cpu_vertices[offset + 1u] = point.y;
            batch.cpu_vertices[offset + 2u] = point.z;
            if (static_cast<size_t>(vertex_index) < batch.cpu_positions.size()) {
                batch.cpu_positions[static_cast<size_t>(vertex_index)] = point;
            }
        }
        for (int vertex_index = 0; vertex_index + 2 < batch.vertex_count; vertex_index += 3) {
            size_t a_offset = static_cast<size_t>(vertex_index) * 23u;
            size_t b_offset = static_cast<size_t>(vertex_index + 1) * 23u;
            size_t c_offset = static_cast<size_t>(vertex_index + 2) * 23u;
            DirectX::XMFLOAT3 a(batch.cpu_vertices[a_offset], batch.cpu_vertices[a_offset + 1u], batch.cpu_vertices[a_offset + 2u]);
            DirectX::XMFLOAT3 b(batch.cpu_vertices[b_offset], batch.cpu_vertices[b_offset + 1u], batch.cpu_vertices[b_offset + 2u]);
            DirectX::XMFLOAT3 c(batch.cpu_vertices[c_offset], batch.cpu_vertices[c_offset + 1u], batch.cpu_vertices[c_offset + 2u]);
            DirectX::XMFLOAT3 ab = sub3(b, a);
            DirectX::XMFLOAT3 ac = sub3(c, a);
            DirectX::XMFLOAT3 normal = normalize3(DirectX::XMFLOAT3(
                ab.y * ac.z - ab.z * ac.y,
                ab.z * ac.x - ab.x * ac.z,
                ab.x * ac.y - ab.y * ac.x));
            for (int corner = 0; corner < 3; ++corner) {
                size_t offset = static_cast<size_t>(vertex_index + corner) * 23u;
                batch.cpu_vertices[offset + 3u] = normal.x;
                batch.cpu_vertices[offset + 4u] = normal.y;
                batch.cpu_vertices[offset + 5u] = normal.z;
                batch.cpu_vertices[offset + 17u] = normal.x;
                batch.cpu_vertices[offset + 18u] = normal.y;
                batch.cpu_vertices[offset + 19u] = normal.z;
            }
        }
        if (context_ && batch.vertex_buffer) {
            D3D11_MAPPED_SUBRESOURCE mapped{};
            HRESULT hr = context_->Map(batch.vertex_buffer.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
            if (SUCCEEDED(hr)) {
                std::memcpy(mapped.pData, batch.cpu_vertices.data(), batch.cpu_vertices.size() * sizeof(float));
                context_->Unmap(batch.vertex_buffer.Get(), 0);
            }
        }
    }

    void reset_cloth_runtime() {
        for (PreviewBatch& batch : batches_) {
            ClothRuntime& cloth = batch.cloth;
            if (!cloth.initialized || cloth.rest_positions.empty()) continue;
            cloth.positions = cloth.rest_positions;
            cloth.previous_positions = cloth.rest_positions;
            cloth.root_motion_initialized = false;
            cloth.non_translation_reanchored = false;
            cloth.last_root_translation = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            apply_cloth_to_batch_vertices(batch);
        }
        cloth_last_step_ = std::chrono::steady_clock::now();
    }

    void step_cloth_simulation() {
        if (!cloth_preview_active()) {
            cloth_last_step_ = std::chrono::steady_clock::now();
            return;
        }
        auto now = std::chrono::steady_clock::now();
        if (cloth_last_step_.time_since_epoch().count() == 0) {
            cloth_last_step_ = now;
            return;
        }
        float dt = static_cast<float>(std::chrono::duration<double>(now - cloth_last_step_).count());
        dt = std::clamp(dt, 1.0f / 240.0f, 1.0f / 30.0f);
        cloth_last_step_ = now;
        const float direction_radians = cloth_state_.wind_direction_degrees * 3.1415926535f / 180.0f;
        DirectX::XMFLOAT3 wind(
            std::cos(direction_radians) * cloth_state_.wind_strength,
            0.0f,
            std::sin(direction_radians) * cloth_state_.wind_strength);
        bool stepped = false;
        for (PreviewBatch& batch : batches_) {
            ClothRuntime& cloth = batch.cloth;
            if (!cloth.initialized || cloth.positions.empty()) continue;
            apply_cloth_root_motion(batch);
            for (size_t index = 0; index < cloth.positions.size(); ++index) {
                float pin = index < cloth.pin_weights.size() ? std::clamp(cloth.pin_weights[index], 0.0f, 1.0f) : 0.0f;
                if (pin >= 0.999f) {
                    cloth.positions[index] = cloth.rest_positions[index];
                    cloth.previous_positions[index] = cloth.rest_positions[index];
                    continue;
                }
                DirectX::XMFLOAT3 current = cloth.positions[index];
                DirectX::XMFLOAT3 previous = cloth.previous_positions[index];
                DirectX::XMFLOAT3 velocity = mul3(sub3(current, previous), std::clamp(1.0f - cloth.damping * dt * 0.35f, 0.0f, 0.995f));
                cloth.previous_positions[index] = current;
                DirectX::XMFLOAT3 acceleration(wind.x * cloth.wind_response, cloth.gravity, wind.z * cloth.wind_response);
                cloth.positions[index] = add3(add3(current, velocity), mul3(acceleration, dt * dt));
            }
            const int iterations = std::clamp(cloth.solver_iterations, 1, 64);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                for (const ClothConstraint& constraint : cloth.constraints) {
                    solve_cloth_constraint(cloth, constraint);
                }
                pin_cloth_particles(cloth);
                if (cloth.collision_enabled && !cloth_colliders_.empty()) {
                    for (size_t index = 0; index < cloth.positions.size(); ++index) {
                        float pin = index < cloth.pin_weights.size() ? cloth.pin_weights[index] : 0.0f;
                        if (pin >= 0.999f) continue;
                        collide_cloth_particle(cloth.positions[index]);
                    }
                }
            }
            apply_cloth_to_batch_vertices(batch);
            stepped = true;
        }
        if (stepped) {
            ++stats_.cloth_simulation_steps;
        }
    }

    bool upload_batches() {
        return upload_batches(batches_, stats_);
    }

    bool upload_batches(std::vector<PreviewBatch>& batches, RendererStats& stats) {
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
            load_batch_texture(batch.base_dds, batch.base_png, batch.base_srv, "base", stats, batch.live_texture_bytes);
            load_batch_texture(batch.normal_dds, batch.normal_png, batch.normal_srv, "normal", stats, batch.live_texture_bytes);
            load_batch_texture(batch.material_dds, L"", batch.material_srv, "material", stats, batch.live_texture_bytes);
            load_batch_texture(batch.occlusion_dds, batch.occlusion_png, batch.occlusion_srv, "occlusion", stats, batch.live_texture_bytes);
            load_batch_texture(batch.roughness_dds, batch.roughness_png, batch.roughness_srv, "roughness", stats, batch.live_texture_bytes);
            load_batch_texture(batch.metalness_dds, batch.metalness_png, batch.metalness_srv, "metalness", stats, batch.live_texture_bytes);
            load_batch_texture(batch.specular_dds, batch.specular_png, batch.specular_srv, "specular", stats, batch.live_texture_bytes);
            load_batch_texture(batch.detail_dds, L"", batch.detail_srv, "detail", stats, batch.live_texture_bytes);
            load_batch_texture(batch.height_dds, batch.height_png, batch.height_srv, "height", stats, batch.live_texture_bytes);
            load_batch_texture(batch.emissive_dds, batch.emissive_png, batch.emissive_srv, "emissive", stats, batch.live_texture_bytes);
            for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
                PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                load_batch_texture(layer.diffuse_dds, L"", layer.diffuse_srv, "layer_base", stats, batch.live_texture_bytes);
                load_batch_texture(layer.mask_dds, L"", layer.mask_srv, "detail", stats, batch.live_texture_bytes);
                load_batch_texture(layer.material_dds, L"", layer.material_srv, "material", stats, batch.live_texture_bytes);
                load_batch_texture(layer.normal_dds, L"", layer.normal_srv, "normal", stats, batch.live_texture_bytes);
                load_batch_texture(layer.height_dds, L"", layer.height_srv, "height", stats, batch.live_texture_bytes);
            }
        }
        stats.texture_ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - texture_start).count();
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
                {"texture_cache_entries", std::to_string(stats.texture_cache_entries)},
                {"texture_cache_releases", std::to_string(stats.texture_cache_releases)},
                {"estimated_texture_bytes", std::to_string(stats.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats.live_texture_bytes)},
                {"skipped", std::to_string(stats.skipped.size())}
            });
        return uploaded_any_geometry;
    }

    void load_batch_texture(
        const std::wstring& dds_path,
        const std::wstring& png_fallback,
        ComPtr<ID3D11ShaderResourceView>& target,
        const char* slot,
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
            stats.failed_textures.push_back(slot_name + "|" + path_text + "|" + stage_text + "|" + hr_text + "|DDS upload failed");
            stats.skipped.push_back(slot_name + " DDS upload failed:" + path_text + ":" + hr_text);
            cdmw_native_diag::event("dds_upload_failed", {{"slot", slot_name}, {"path", path_text}, {"stage", stage_text}, {"hresult", hr_text}});
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
            stats.failed_textures.push_back(slot_name + "|" + path_text + "|" + stage_text + "|" + hr_text + "|PNG fallback failed");
            stats.skipped.push_back(slot_name + " PNG fallback failed:" + path_text + ":" + hr_text);
            cdmw_native_diag::event("png_fallback_failed", {{"slot", slot_name}, {"path", path_text}, {"stage", stage_text}, {"hresult", hr_text}});
        }
    }

    bool load_srv_from_file(
        const std::wstring& path,
        bool dds,
        ComPtr<ID3D11ShaderResourceView>& target,
        TextureLoadInfo* info,
        DirectX::CREATETEX_FLAGS create_flags,
        RendererStats& stats,
        HRESULT* failed_hr = nullptr,
        std::string* failed_stage = nullptr,
        std::uint64_t* loaded_bytes = nullptr) {
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

    HWND hwnd_{};
    Args args_;
    std::vector<PreviewBatch> batches_;
    std::vector<ClothCollider> cloth_colliders_;
    ClothPreviewState cloth_state_;
    SkeletonOverlayState skeleton_overlay_;
    RendererStats& stats_;
    ViewSettings view_settings_;
    RenderTuning render_tuning_;
    bool view_settings_overridden_ = false;
    bool render_tuning_overridden_ = false;
    LONG width_ = 1;
    LONG height_ = 1;
    float yaw_ = kDefaultYawDegrees;
    float pitch_ = kDefaultPitchDegrees;
    bool fit_to_view_ = true;
    float zoom_factor_ = 1.0f;
    float distance_ = kFitDistance;
    float pan_x_ = 0.0f;
    float pan_y_ = 0.0f;
    float pan_z_ = 0.0f;
    PreviewCameraState reference_camera_;
    std::string display_mode_ = "replacement_only";
    float side_by_side_split_ratio_ = 0.5f;
    bool side_by_side_split_drag_active_ = false;
    bool side_by_side_split_hover_ = false;
    std::set<int> hidden_source_submeshes_;
    bool icon_capture_mode_ = false;
    AlignmentState alignment_;
    SourcePartInteractionState source_part_;
    MeshEditState mesh_edit_;
    int drag_mode_ = 0;
    UINT drag_button_ = 0;
    PreviewViewRole drag_view_role_ = PreviewViewRole::All;
    int last_mouse_x_ = 0;
    int last_mouse_y_ = 0;
    int cursor_x_ = 0;
    int cursor_y_ = 0;
    bool first_frame_started_ = false;
    bool first_frame_reported_ = false;
    bool render_requested_ = true;
    std::uint64_t frame_count_ = 0;
    std::uint64_t render_request_count_ = 0;
    std::uint64_t render_suppressed_count_ = 0;
    std::uint64_t parent_unresponsive_count_ = 0;
    std::string parent_health_ = "ok";
    std::chrono::steady_clock::time_point first_frame_timer_{};
    std::chrono::steady_clock::time_point cloth_last_step_{};
    D3D_FEATURE_LEVEL feature_level_{};
    DirectX::XMFLOAT4 clear_color_{0.03f, 0.04f, 0.05f, 1.0f};
    ComPtr<ID3D11Device> device_;
    ComPtr<ID3D11DeviceContext> context_;
    ComPtr<IDXGISwapChain> swap_chain_;
    ComPtr<ID3D11RenderTargetView> render_target_;
    ComPtr<ID3D11DepthStencilView> depth_view_;
    UINT msaa_sample_count_ = 1;
    ComPtr<ID3D11VertexShader> vertex_shader_;
    ComPtr<ID3D11PixelShader> pixel_shader_;
    ComPtr<ID3D11PixelShader> overlay_pixel_shader_;
    ComPtr<ID3D11InputLayout> input_layout_;
    ComPtr<ID3D11VertexShader> vertex_dot_shader_;
    ComPtr<ID3D11PixelShader> vertex_dot_pixel_shader_;
    ComPtr<ID3D11InputLayout> vertex_dot_input_layout_;
    ComPtr<ID3D11Buffer> constants_;
    ComPtr<ID3D11SamplerState> sampler_;
    ComPtr<ID3D11RasterizerState> rasterizer_;
    ComPtr<ID3D11RasterizerState> cull_rasterizer_;
    ComPtr<ID3D11RasterizerState> wireframe_rasterizer_;
    ComPtr<ID3D11DepthStencilState> depth_state_;
    ComPtr<ID3D11DepthStencilState> overlay_depth_state_;
    std::map<std::wstring, ComPtr<ID3D11ShaderResourceView>> srv_cache_;
    std::map<std::wstring, TextureLoadInfo> texture_info_cache_;
    int texture_cache_releases_ = 0;
    std::uint64_t estimated_texture_bytes_ = 0;
    std::uint64_t active_texture_bytes_ = 0;
    fs::path pending_package_dir_;
    fs::path pending_status_file_;
    fs::path pending_capture_path_;
    std::string pending_mesh_edit_vertices_payload_;
    fs::path pending_mesh_edit_vertices_file_;
    bool pending_mesh_edit_vertices_delete_after_ = false;
    bool pending_reset_view_ = false;
    std::uint64_t model_generation_ = 0;
    mutable std::uint64_t mesh_edit_cache_generation_ = 0;
    mutable MeshEditScreenVertexCache mesh_edit_screen_vertex_cache_;
    mutable MeshEditDepthMaskCache mesh_edit_depth_mask_cache_;
};

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
    DWORD window_style = WS_OVERLAPPEDWINDOW | WS_VISIBLE;
    if (parent_hwnd && IsWindow(parent_hwnd)) {
        GetClientRect(parent_hwnd, &parent_rect);
        window_x = 0;
        window_y = 0;
        window_width = std::max<LONG>(1, parent_rect.right - parent_rect.left);
        window_height = std::max<LONG>(1, parent_rect.bottom - parent_rect.top);
        window_style = WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN;
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
        if (running) {
            renderer.process_pending_commands();
            if (renderer.should_render()) {
                const bool window_renderable = IsWindowVisible(hwnd) && !IsIconic(hwnd);
                if (parent_renderable && window_renderable) {
                    renderer.render();
                } else {
                    renderer.note_render_suppressed(parent_renderable ? "window_not_visible" : "parent_not_renderable");
                    MsgWaitForMultipleObjects(0, nullptr, FALSE, kIdleWaitMs, QS_ALLINPUT);
                }
            } else {
                MsgWaitForMultipleObjects(0, nullptr, FALSE, kIdleWaitMs, QS_ALLINPUT);
            }
        }
    }
    renderer.release_model_resources(close_reason.c_str());
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
    write_status(args.status_file, closed_payload(stats, close_reason));
    cdmw_native_diag::event("clean_shutdown", {{"reason", close_reason}});
    return 0;
}

int wmain(int argc, wchar_t** argv) {
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
        if (FAILED(hr)) {
            cdmw_native_diag::event("self_test_error", {{"hresult", std::to_string(static_cast<unsigned int>(hr))}});
        } else if (!shader_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "shader_compile_failed"}, {"message", shader_error}});
        } else if (!selection_binary_ok) {
            cdmw_native_diag::event("self_test_error", {{"reason", "selection_binary_descriptor_failed"}});
        } else {
            cdmw_native_diag::event("self_test_ok", {{"feature_level", std::to_string(static_cast<unsigned int>(feature))}, {"shader", "ok"}, {"selection_binary", "ok"}});
        }
        const bool ok = SUCCEEDED(hr) && shader_ok && selection_binary_ok;
        std::cout << "{\"event\":\"self_test\",\"backend\":\"D3D11\",\"ok\":" << (ok ? "true" : "false") << "}\n";
        return ok ? 0 : 2;
    }
    if (args.backend != L"d3d11" && args.backend != L"D3D11") {
        write_status(args.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"only D3D11 backend is supported by this native host\"}");
        cdmw_native_diag::event("startup_error", {{"reason", "unsupported backend"}, {"backend", cdmw_native_diag::wide_to_utf8_diag(args.backend)}});
        return 1;
    }
    return run_host(args);
}
