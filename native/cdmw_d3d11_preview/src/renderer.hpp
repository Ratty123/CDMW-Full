#pragma once

#include "d3d_preview_types.hpp"

namespace cdmw_d3d11_preview {

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
        std::string display_mode);

    ~Renderer() ;

    bool initialize() ;

    void request_render() ;

    bool should_render() const ;

    bool device_lost() const ;

    std::string capture_back_buffer_to_png(const fs::path& output) ;

    void note_render_suppressed(const char* reason) ;

    void set_parent_health(const std::string& health, std::uint64_t unresponsive_count) ;

    void prune_srv_cache_if_needed(const char* reason) ;

    void release_model_resources(const char* reason) ;

    void reset_mesh_edit_revision_state() ;

    bool load_package(const fs::path& package_dir, const fs::path& status_file, bool reset_view_state) ;

    bool clear_preview(const fs::path& status_file) ;

    bool handle_window_message(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) ;

    void render() ;

    bool process_pending_commands() ;

private:
    std::vector<std::string> missing_package_paths(const std::vector<PreviewBatch>& batches) const;
    bool handle_pointer_down_or_move(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result);
    void set_preview_batch_lighting_constants(
        ConstantBuffer& constants,
        const PreviewBatch& batch,
        const DirectX::XMMATRIX& normal_source_world,
        bool mesh_edit_flat) const;
    void append_mesh_edit_topology_overlay(
        const PreviewRenderView& view,
        const MeshEditDepthMaskCache* depth_mask,
        std::vector<float>& vertices);
    bool handle_package_commands(const std::string& command, const std::string& payload, bool& matched);
    bool handle_material_commands(const std::string& command, const std::string& payload, bool& matched);
    bool handle_interaction_commands(const std::string& command, const std::string& payload, bool& matched);
    bool handle_edit_state_commands(const std::string& command, const std::string& payload, bool& matched);
    bool handle_selection_commands(const std::string& command, const std::string& payload, bool& matched);
    bool handle_edit_update_commands(const std::string& command, const std::string& payload, bool& matched);
    struct PositionUpdate;
    struct NormalUpdate;
    struct UvUpdate;
    struct ParsedUpdateGroup;
    auto parse_mesh_vertex_update_groups(
        const std::string& payload,
        std::set<int>& group_source_submeshes) const -> std::vector<ParsedUpdateGroup>;
    int apply_mesh_vertex_update_groups(
        const std::vector<ParsedUpdateGroup>& groups,
        const std::set<int>& group_source_submeshes);
    int remove_replaced_mesh_batches(
        const std::string& payload,
        const std::vector<std::string>& groups,
        bool replace_all);
    void ensure_triangle_replacement_batch(const TriangleReplacementGroup& group);
    int apply_triangle_replacement_group(const TriangleReplacementGroup& group);
    DirectX::XMFLOAT3 transform_replacement_position(
        const PreviewBatch& batch,
        const TriangleReplacementGroup& group,
        DirectX::XMFLOAT3 position) const;

    void unbind_render_outputs_for_device_loss() ;

    void handle_device_loss(const char* stage, HRESULT hr) ;

    void handle_render_failure(const char* stage, HRESULT hr) ;

    bool process_pending_mesh_edit_vertex_update() ;

    void cleanup_mesh_edit_vertices_file(const fs::path& file_path, bool delete_after) const ;

    void send_mesh_edit_vertices_ack(
        std::uint64_t revision,
        const char* status,
        int changed_vertices,
        bool payload_file,
        const char* reason) const ;

    bool accept_mesh_edit_vertices_revision(
        std::uint64_t revision,
        const std::string& payload = {},
        const fs::path& file_path = {},
        bool delete_after = false) ;

    void queue_mesh_edit_vertices_payload(const std::string& payload, std::uint64_t revision) ;

    void queue_mesh_edit_vertices_file(const fs::path& payload_file, bool delete_after, std::uint64_t revision) ;

    bool batch_is_reference(const PreviewBatch& batch) const ;

    bool has_reference_batches() const ;

    static D3D11_VIEWPORT viewport_rect(float x, float y, float width, float height) ;

    D3D11_VIEWPORT full_viewport() const ;

    float side_by_side_reference_width() const ;

    D3D11_VIEWPORT replacement_editor_viewport() const ;

    std::vector<PreviewRenderView> active_render_views() const ;

    bool batch_visible_in_view(const PreviewBatch& batch, PreviewViewRole role) const ;

    bool side_by_side_workspace_active() const ;

    bool side_by_side_splitter_hit_test(int x, int /*y*/) const ;

    void set_side_by_side_split_from_x(int x) ;

    void set_side_by_side_split_ratio(float ratio) ;

    PreviewViewRole input_view_role_at(int x, int /*y*/) const ;

    const PreviewCameraState& reference_camera() const ;

    PreviewCameraState& reference_camera() ;

    PreviewCameraState replacement_camera() const ;

    void set_replacement_camera(const PreviewCameraState& camera) ;

    PreviewCameraState camera_for_view_role(PreviewViewRole role) const ;

    void set_camera_for_role(PreviewViewRole role, const PreviewCameraState& camera) ;

    DirectX::XMMATRIX world_matrix_for_camera(const PreviewCameraState& camera) const ;

    DirectX::XMMATRIX world_matrix_for_view_role(PreviewViewRole role) const ;

    float distance_for_view_role(PreviewViewRole role) const ;

    DirectX::XMMATRIX view_projection_matrix_for_viewport(const D3D11_VIEWPORT& viewport, float distance) const ;

    static bool alignment_transform_value_active(
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) ;

    bool alignment_global_transform_active() const ;

    bool alignment_part_transform_active(const AlignmentState::PartTransform& transform) const ;

    bool alignment_preview_transform_active() const ;

    bool alignment_non_translation_transform_active() const ;

    bool alignment_batch_editable(const PreviewBatch& batch) const ;

    bool alignment_batch_active(const PreviewBatch& batch) const ;

    bool alignment_origin_for_batches(DirectX::XMFLOAT3& origin, const std::set<int>* source_filter) const ;

    bool alignment_handle_origin_base(DirectX::XMFLOAT3& origin) const ;

    bool alignment_global_origin_base(DirectX::XMFLOAT3& origin) const ;

    bool alignment_part_origin_base(int source_submesh_index, DirectX::XMFLOAT3& origin) const ;

    static DirectX::XMMATRIX alignment_transform_matrix(
        const DirectX::XMFLOAT3& origin,
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) ;

    DirectX::XMMATRIX alignment_preview_transform_for_batch(const PreviewBatch& batch) const ;

    static bool batch_uses_source_normalization(const PreviewBatch& batch) ;

    static DirectX::XMMATRIX source_to_preview_normalization_transform(const PreviewBatch& batch) ;

    static DirectX::XMFLOAT3 source_to_preview_position_for_batch(const PreviewBatch& batch, const DirectX::XMFLOAT3& position) ;

    DirectX::XMMATRIX mesh_edit_source_world_transform_for_batch(const PreviewBatch& batch) const ;

    DirectX::XMFLOAT3 transformed_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position) const ;

    static void append_line_vertex(
        std::vector<float>& vertices,
        float x,
        float y,
        float z,
        float r,
        float g,
        float b
    ) ;

    void draw_colored_lines(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) ;

    void draw_colored_triangles(const std::vector<float>& vertices, const DirectX::XMMATRIX& mvp, bool no_depth) ;

    bool manifest_original_frame_grid_active() const ;

    float workspace_grid_y_for_view(const PreviewRenderView& view) const ;

    void draw_workspace_grid(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) ;

    void draw_alignment_axes(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) ;

    static DirectX::XMFLOAT3 transform_coord(const DirectX::XMFLOAT3& point, const DirectX::XMMATRIX& matrix) ;

    static void append_debug_line(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& a,
        const DirectX::XMFLOAT3& b,
        float r,
        float g,
        float blue
    ) ;

    static void append_debug_cross(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& point,
        float size,
        float r,
        float g,
        float blue
    ) ;

    static void append_debug_aabb(
        std::vector<float>& vertices,
        const DirectX::XMFLOAT3& min_corner,
        const DirectX::XMFLOAT3& max_corner,
        float r,
        float g,
        float blue
    ) ;

    void draw_cloth_debug_overlays(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) ;

    void draw_skeleton_overlay(const PreviewRenderView& view, const DirectX::XMMATRIX& world_view_projection) ;

    void draw_preview_batch(
        PreviewBatch& batch,
        const DirectX::XMMATRIX& mvp,
        const DirectX::XMMATRIX& normal_source_world,
        const DirectX::XMFLOAT4& editor_tint,
        bool mesh_edit_flat
    ) ;

    bool mesh_edit_overlay_active_for_view(const PreviewRenderView& view) const ;

    bool mesh_edit_source_allowed(int source_submesh_index) const ;

    bool mesh_edit_batch_editable_in_view(const PreviewBatch& batch, const PreviewRenderView& view) const ;

    static bool mesh_edit_preserve_materials_for_batch(const PreviewBatch& batch) ;

    std::pair<int, int> mesh_edit_source_key(const PreviewBatch& batch, size_t vertex_index) const ;

    void rebuild_batch_source_vertex_lookup(PreviewBatch& batch) const ;

    void rebuild_batch_source_face_vertex_lookup(PreviewBatch& batch) const ;

    bool mesh_edit_source_vertex_selected(const PreviewBatch& batch, size_t vertex_index) const ;

    std::pair<int, int> mesh_edit_source_face_key(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const ;

    bool mesh_edit_source_face_selected(const PreviewBatch& batch, size_t triangle_index, size_t base_vertex_index) const ;

    bool mesh_edit_source_edge_selected(const std::pair<int, int>& left, const std::pair<int, int>& right) const ;

    bool project_batch_position_for_view(
        const PreviewBatch& batch,
        const DirectX::XMFLOAT3& position,
        const PreviewRenderView& view,
        float& screen_x,
        float& screen_y,
        float* depth_z = nullptr
    ) const ;

    std::string mesh_edit_screen_vertex_cache_key(const PreviewRenderView& view) const ;

    void invalidate_mesh_edit_caches() const ;

    bool mesh_edit_depth_filter_enabled() const ;

    const std::vector<MeshEditScreenVertex>& mesh_edit_screen_vertices_for_view(const PreviewRenderView& view) const ;

    static float edge_function(float ax, float ay, float bx, float by, float cx, float cy) ;

    const MeshEditDepthMaskCache& mesh_edit_depth_mask_for_view(const PreviewRenderView& view) const ;

    bool mesh_edit_screen_vertex_visible_in_depth_mask(
        const MeshEditScreenVertex& screen_vertex,
        const MeshEditDepthMaskCache& depth_mask
    ) const ;

    void draw_mesh_edit_vertex_dots_instanced(
        const PreviewRenderView& view,
        const std::vector<MeshEditScreenVertex>& screen_vertices,
        bool no_depth) ;

    void draw_mesh_edit_overlay(const PreviewRenderView& view) ;

    void draw_highlight_bounds_overlay(const PreviewRenderView& view) ;

    bool reference_material_tint_allowed() const ;

    void draw_render_view(const PreviewRenderView& view) ;

    void draw_side_by_side_splitter_overlay() ;

    void update_runtime_stats(RendererStats& stats) ;

    void update_runtime_stats() ;

    std::uint64_t active_bound_texture_bytes() const ;

    static std::wstring texture_file_identity(const std::wstring& path, bool* stable_file_id = nullptr) ;

    static std::wstring texture_cache_key(
        const std::wstring& path,
        bool dds,
        DirectX::CREATETEX_FLAGS create_flags) ;

    static float current_display_scale(float distance) ;

    float world_units_per_pixel() const ;

    float world_units_per_pixel_for_role(PreviewViewRole role) const ;

    DirectX::XMMATRIX current_world_matrix() const ;

    DirectX::XMMATRIX current_view_projection_matrix() const ;

    DirectX::XMMATRIX current_mvp_matrix() const ;

    bool project_position(const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const ;

    bool project_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const ;

    bool alignment_handle_origin(DirectX::XMFLOAT3& origin) const ;

    std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> alignment_axis_points() const ;

    static float distance_to_segment(float x, float y, const ScreenPoint& start, const ScreenPoint& end) ;

    std::string alignment_axis_at(int x, int y) const ;

    std::string alignment_rotation_handle_at(int x, int y) const ;

    DirectX::XMFLOAT3 alignment_screen_drag_delta(int delta_x, int delta_y, float units_per_pixel) const ;

    void send_alignment_vector_event(const char* event_name, const DirectX::XMFLOAT3& value) const ;

    bool alignment_drag_change_due(std::chrono::steady_clock::time_point& last_sent) const ;

    void send_alignment_started_event(const char* mode, const char* axis) const ;

    void drop_pending_package_reload(const char* reason) ;

    bool begin_alignment_drag(WPARAM wparam, int x, int y) ;

    bool update_alignment_translation_drag(int x, int y, WPARAM wparam) ;

    bool update_alignment_rotation_drag(int x, int y, WPARAM wparam) ;

    bool update_alignment_drag(int x, int y, WPARAM wparam) ;

    void update_alignment_hover(int x, int y) ;

    bool finish_alignment_drag(int x, int y, WPARAM wparam) ;

    bool cancel_alignment_drag() ;

    void draw_alignment_overlay_gdi() const ;

    int source_part_at(int x, int y, float radius_pixels) const ;

    void send_source_part_event(const char* event_name, int source_submesh_index) const ;

    void send_source_part_context_event(int source_submesh_index, int x, int y) const ;

    void send_source_part_screen_selection_event(int x, int y) ;

    void send_source_part_screen_context_event(int x, int y) ;

    void update_source_part_hover(int x, int y) ;

    void begin_source_part_click(WPARAM wparam, int x, int y) ;

    void finish_source_part_click(int x, int y) ;

    bool request_source_part_context(WPARAM wparam, int x, int y) ;

    std::string mesh_edit_screen_drag_json(int start_x, int start_y, int end_x, int end_y) const ;

    std::string mesh_edit_screen_radius_json(float radius_pixels) const ;

    std::string mesh_edit_source_projection_overrides_json() const ;

    std::string mesh_edit_screen_brush_json(int x, int y, float radius_pixels, bool include_source_filter = true) const ;

    std::string mesh_edit_screen_region_json(int x, int y) const ;

    std::string mesh_edit_payload_json(
        int x,
        int y,
        bool invert,
        bool include_screen_selection = false) const ;

    void send_mesh_edit_event(const char* event_name, const std::string& payload_json) const ;

    void add_mesh_edit_face_vertices_to_selection(int source_submesh, const std::set<int>& source_faces) ;

    void add_mesh_edit_source_vertices_to_selection(int source_submesh) ;

    static std::tuple<int, int, int> mesh_edit_edge_key(int source_submesh, int left, int right) ;

    void send_mesh_edit_screen_brush_selection_event(int x, int y) ;

    void send_mesh_edit_screen_region_selection_event(int x, int y) ;

    void send_mesh_edit_selection_event(bool include_screen_brush = false) ;

    int update_mesh_edit_vertices_from_payload(const std::string& payload) ;

    void flush_pending_mesh_edit_vertex_uploads() ;

    std::pair<int, int> replace_mesh_edit_triangles_from_payload(const std::string& payload) ;

    static std::string mesh_edit_selection_operation_from_modifiers(WPARAM wparam) ;

    void apply_mesh_edit_brush_selection(int x, int y) ;

    bool mesh_edit_preview_event_due(bool force_preview) const ;

    void mark_mesh_edit_preview_event() ;

    void apply_mesh_edit_region_selection(int x, int y) ;

    void finish_mesh_edit_selection_drag(int x, int y) ;

    bool begin_mesh_edit_drag(WPARAM wparam, int x, int y) ;

    bool update_mesh_edit_drag(int x, int y, bool force_preview = false) ;

    bool finish_mesh_edit_drag(int x, int y) ;

    bool cancel_mesh_edit_drag() ;

    void send_json_event(const std::string& payload) const ;

    void send_view_event(const char* reason, PreviewViewRole role = PreviewViewRole::Replacement) const ;

    void send_side_by_side_split_event(const char* reason) const ;

    bool handle_copy_data(const COPYDATASTRUCT* cds) ;

    static void reset_camera(PreviewCameraState& camera) ;

    void reset_replacement_camera() ;

    void reset_camera_for_role(PreviewViewRole role) ;

    void reset_view() ;

    void cancel_mouse_interaction(bool release_capture = true) ;

    void set_zoom_factor(float zoom_factor) ;

    void set_fit_to_view(bool fit_to_view) ;

    void begin_mouse_drag(UINT msg, WPARAM wparam, int x, int y) ;

    bool begin_side_by_side_split_drag(int x, int y) ;

    bool update_side_by_side_split_drag(int x, int y) ;

    void update_mouse_drag(int x, int y) ;

    void end_mouse_drag(UINT msg) ;

    bool finish_side_by_side_split_drag(int x, int y) ;

    void apply_wheel_delta(int wheel_delta, int x, int y) ;

    bool create_render_targets() ;

    bool resize_if_needed() ;

    bool create_pipeline() ;

    bool create_sampler_state() ;

    static DirectX::XMFLOAT3 add3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) ;

    static DirectX::XMFLOAT3 sub3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) ;

    static DirectX::XMFLOAT3 mul3(const DirectX::XMFLOAT3& a, float scale) ;

    static float dot3(const DirectX::XMFLOAT3& a, const DirectX::XMFLOAT3& b) ;

    static float length3(const DirectX::XMFLOAT3& value) ;

    static DirectX::XMFLOAT3 normalize3(
        const DirectX::XMFLOAT3& value,
        const DirectX::XMFLOAT3& fallback = DirectX::XMFLOAT3(0.0f, 0.0f, 1.0f)) ;

    bool load_cloth_runtime(PreviewBatch& batch, RendererStats& stats) ;

    bool cloth_preview_active() const ;

    static void collide_point_with_sphere(DirectX::XMFLOAT3& point, const DirectX::XMFLOAT3& center, float radius) ;

    static void collide_point_with_capsule(DirectX::XMFLOAT3& point, const ClothCollider& collider) ;

    static void collide_point_with_aabb(DirectX::XMFLOAT3& point, const ClothCollider& collider) ;

    void collide_cloth_particle(DirectX::XMFLOAT3& point) const ;

    void solve_cloth_constraint(ClothRuntime& cloth, const ClothConstraint& constraint) ;

    static void pin_cloth_particles(ClothRuntime& cloth) ;

    DirectX::XMFLOAT3 cloth_root_translation_for_batch(const PreviewBatch& batch) const ;

    void apply_cloth_root_motion(PreviewBatch& batch) ;

    void apply_cloth_to_batch_vertices(PreviewBatch& batch) ;

    void reset_cloth_runtime() ;

    void step_cloth_simulation() ;

    bool upload_batches() ;

    bool upload_batches(std::vector<PreviewBatch>& batches, RendererStats& stats) ;

    void load_batch_texture(
        const std::wstring& dds_path,
        const std::wstring& png_fallback,
        ComPtr<ID3D11ShaderResourceView>& target,
        const char* slot,
        bool required_slot,
        RendererStats& stats,
        std::uint64_t& bound_texture_bytes) ;

    bool load_srv_from_file(
        const std::wstring& path,
        bool dds,
        ComPtr<ID3D11ShaderResourceView>& target,
        TextureLoadInfo* info,
        DirectX::CREATETEX_FLAGS create_flags,
        RendererStats& stats,
        HRESULT* failed_hr = nullptr,
        std::string* failed_stage = nullptr,
        std::uint64_t* loaded_bytes = nullptr) ;

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
    PreviewRenderedCameraEvidence last_rendered_camera_evidence_;
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
    bool device_lost_ = false;
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
    std::uint64_t pending_mesh_edit_vertices_revision_ = 0;
    std::uint64_t last_applied_mesh_edit_revision_ = 0;
    bool pending_reset_view_ = false;
    std::uint64_t model_generation_ = 0;
    mutable std::uint64_t mesh_edit_cache_generation_ = 0;
    mutable MeshEditScreenVertexCache mesh_edit_screen_vertex_cache_;
    mutable MeshEditDepthMaskCache mesh_edit_depth_mask_cache_;
};

}  // namespace cdmw_d3d11_preview
