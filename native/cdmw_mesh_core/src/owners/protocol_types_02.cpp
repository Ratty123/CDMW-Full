struct MeshEditorSubmeshDelta {
    MeshEditorChannelDelta<Vec3> vertices;
    MeshEditorChannelDelta<std::array<int, 3>> faces;
    MeshEditorChannelDelta<int> source_face_indices;
    MeshEditorChannelDelta<Vec3> normals;
    MeshEditorChannelDelta<Vec2> uvs;
    MeshEditorChannelDelta<Vec3> tangents;
    MeshEditorChannelDelta<double> tangent_signs;
    MeshEditorChannelDelta<std::vector<int>> bone_indices;
    MeshEditorChannelDelta<std::vector<double>> bone_weights;
    MeshEditorChannelDelta<int> source_vertex_map;
    MeshEditorChannelDelta<int> source_vertex_offsets;
    std::string before_name;
    std::string after_name;
    std::string before_material;
    std::string after_material;
    std::string before_texture;
    std::string after_texture;
    JsonValue before_extra_attrs;
    JsonValue after_extra_attrs;
    bool metadata_changed = false;
};

struct MeshEditorPreEditChannels {
    std::vector<std::array<int, 3>> faces;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    std::string name;
    std::string material;
    std::string texture;
    JsonValue extra_attrs;
    bool capture_faces = false;
    bool capture_normals = false;
    bool capture_uvs = false;
    bool capture_tangents = false;
    bool capture_metadata = false;
};

struct MeshMorphSparseFieldRuntime {
    std::vector<int> vertex_indices;
    std::vector<Vec3> deltas;
};

struct MeshMorphDefinitionRuntime {
    std::string definition_id;
    std::string label;
    std::string category;
    double min_percent = -100.0;
    double max_percent = 100.0;
    double default_percent = 0.0;
    std::map<int, MeshMorphSparseFieldRuntime> fields;
    std::map<int, MeshMorphSparseFieldRuntime> post_refit_fields;
};

struct MeshMorphProfileRuntime {
    std::string profile_id;
    std::string name;
    std::string topology_fingerprint;
    std::map<std::string, MeshMorphDefinitionRuntime> definitions;
};

struct MeshRefitVertexBindingRuntime {
    int garment_submesh_index = -1;
    int garment_vertex_index = -1;
    int driver_submesh_index = -1;
    std::array<int, 3> driver_vertices{-1, -1, -1};
    std::array<double, 3> barycentric{1.0, 0.0, 0.0};
    double distance = 0.0;
    // Signed standoff from the bound triangle, in the baseline face frame. The
    // refit displaces a garment vertex by its driver point's translation plus
    // normal_height * (current normal - baseline_normal), so the standoff turns
    // with a rotating body instead of staying pinned to a world direction. Both
    // fields describe the same rest state and are only ever written together, by
    // refit_bind_normal_height_native. A zero baseline_normal means the baseline
    // face was degenerate and the normal term is disabled for this binding.
    Vec3 baseline_normal{0.0, 0.0, 0.0};
    double normal_height = 0.0;
    Vec3 rigid_local_offset{0.0, 0.0, 0.0};
    bool rigid_frame_valid = false;
};

struct MeshRefitIslandSettingsRuntime {
    std::vector<int> face_indices;
    bool enabled = true;
    double intensity_percent = 100.0;
    std::string mode = "surface";
    double clearance_percent = 0.0;
    double tightness_percent = 0.0;
    bool tightness_initialized = true;
    double skin_pull_percent = 0.0;
};

struct MeshRefitGarmentSettingsRuntime {
    bool enabled = true;
    double intensity_percent = 100.0;
    std::string mode = "surface";
    double clearance_percent = 0.0;
    double tightness_percent = 0.0;
    bool tightness_initialized = true;
    // Authored-body fits only: how much of the outfit's own gap to the skin to close.
    double skin_pull_percent = 0.0;
    std::vector<MeshRefitIslandSettingsRuntime> island_settings;
};

// The body a garment was authored on, given in two poses of one topology: as
// authored, and retargeted by the caller into the driver's bind space. Only the
// reference-body fitter reads it; it is immutable and shared through history.
struct MeshRefitReferenceBodyRuntime {
    std::string label;
    std::vector<Vec3> source_positions;
    std::vector<Vec3> fitted_positions;
    std::vector<std::array<int, 3>> faces;
};

// Skin weights a Fit to reference body hands from the driver to garment
// vertices near it. Bones are the driver skeleton's; each garment Part maps
// them onto slots of its own PAC palette (the caller resolves names and
// nearest ancestors), so a palette never grows. Capacities are per vertex:
// six influences, or four on cloth-simulated records.
struct MeshRefitWeightTransferRuntime {
    std::map<int, std::vector<int>> driver_bones;   // driver Part: palette slot -> driver bone, or -1
    std::map<int, std::vector<int>> garment_slots;  // garment Part: driver bone -> palette slot, or -1
    std::map<int, std::vector<int>> capacities;     // garment Part: vertex -> influence capacity
    // How far each authored body vertex and each garment vertex move in a few
    // test poses of the garments' own skeleton, as authored, flattened as
    // (vertex, pose, axis). Cloth that stays behind the skin beneath it there
    // was made not to follow that skin.
    std::size_t motion_poses = 0;
    std::vector<double> reference_motion;
    std::map<int, std::vector<double>> garment_motion;
};

struct MeshRefitRuntime {
    // Evaluation-only domain boundaries. Persisted overrides own their source faces.
    std::set<int> independent_island_parts;
    // Inferred solid attachments may still join touching assembly pieces.
    // This evaluation-only map is never persisted as a user override.
    std::map<int, std::set<std::vector<int>>> automatic_rigid_islands;
    std::map<int, int> automatic_rigid_parts;
    // Split rigid islands can retain small assembly caps when their controls match.
    std::map<int, int> rigid_island_source_parts;
    std::set<int> driver_submesh_indices;
    std::set<int> garment_submesh_indices;
    std::map<int, std::vector<Vec3>> driver_baseline_positions;
    std::vector<MeshRefitVertexBindingRuntime> bindings;
    std::map<int, MeshRefitGarmentSettingsRuntime> garment_settings;
    // A missing mask means full influence; a present sparse row defaults to zero.
    std::map<int, std::map<int, double>> vertex_masks;
    // Restrictions are scoped to each garment; missing entries permit every driver face.
    std::map<int, std::map<int, std::set<int>>> garment_regions;
    // Output exclusions captured at binding. An empty face set excludes the
    // whole garment; editable geometry and user fitting settings remain intact.
    std::map<int, std::set<int>> excluded_faces;
    double driver_diagonal = 0.0;
    double maximum_distance = 0.0;
    double p95_distance = 0.0;
    double warning_distance = 0.0;
    bool distance_warning = false;
    long long driver_triangle_count = 0;
    long long candidate_triangle_tests = 0;
    // Present only after Fit to reference body. Garments are then transferred
    // from this body onto the driver instead of following their bindings.
    std::shared_ptr<const MeshRefitReferenceBodyRuntime> reference_body;
    // Present only while that Fit also takes skin weights from the driver.
    std::shared_ptr<const MeshRefitWeightTransferRuntime> weight_transfer;
};

struct MeshMorphRuntime {
    std::shared_ptr<const MeshMorphProfileRuntime> profile;
    std::string preset_id;
    std::map<std::string, double> values;
    std::map<int, std::vector<Vec3>> current_layer;
    // Preserve exact neutral coordinates across preview arithmetic. The visible
    // anchor distinguishes subsequent sculpt edits from layer roundoff.
    std::map<int, std::vector<Vec3>> neutral_positions;
    std::map<int, std::vector<Vec3>> composed_positions;
    // Authored smoothing boundaries must survive a preview that temporarily
    // flattens a hard edge. Share the immutable reference through preview history.
    std::map<int, std::shared_ptr<const std::vector<Vec3>>> neutral_normals;
    // Garment skin rows from before a weight-transferring Fit, restored when
    // the transfer ends (Reset, a plain Fit) and dropped by Bake.
    std::map<int, std::shared_ptr<const BoneAssignments>> neutral_bones;
    std::set<int> driver_submesh_indices;
    std::shared_ptr<const MeshRefitRuntime> refit;
    bool unbaked = false;
    long long state_revision = 0;
    std::string change_id;
    std::string active_change_id;
    std::string active_definition_id;
    int active_change_update_count = 0;
};

struct MeshEditorHistoryEntry {
    // Topology units retain one reversible affected-submesh snapshot. Applying
    // the unit swaps current state back into this map for redo.
    std::map<int, MeshSessionSubmesh> before;
    std::map<int, MeshEditorSubmeshDelta> deltas;
    std::set<int> absent_before;
    // Delete Part keys, numbered as before the delete. Their removal shifted
    // every later key down, so history re-inserts and re-erases with the same
    // shift instead of filling or punching a gap.
    std::set<int> deleted_part_keys;
    std::map<int, int> append_source_indices;
    std::string operation;
    std::string stroke_id;
    int stroke_update_count = 0;
    bool topology_changed = false;
    MeshEditorSelection selection_before;
    bool selection_snapshot = false;
    std::shared_ptr<const MeshMorphRuntime> morph_before;
    std::shared_ptr<const MeshMorphRuntime> morph_after;
    bool morph_state_changed = false;
};

struct MeshEditorStroke {
    bool active = false;
    std::string stroke_id;
    std::string operation;
    std::string tool;
    int update_count = 0;
    // Grab strokes keep the initial brush footprint stable while the cursor moves.
    std::map<int, std::map<int, double>> grab_weights;
    std::map<int, Vec3> grab_centers;
};

struct MeshEditorClipboardFragment {
    int source_index = -1;
    MeshSessionSubmesh submesh;
};

struct MeshEditorSession {
    std::string native_session_id;
    MeshEditorSelection selection;
    MeshEditorStroke active_stroke;
    std::vector<MeshEditorClipboardFragment> clipboard;
    std::vector<MeshEditorHistoryEntry> undo_stack;
    std::vector<MeshEditorHistoryEntry> redo_stack;
    int topology_revision = 0;
    int selection_revision = 0;
    int edit_revision = 0;
    int stroke_revision = 0;
    long long morph_state_revision = 0;
    std::shared_ptr<MeshMorphRuntime> morph = std::make_shared<MeshMorphRuntime>();
    // Diagnostics from the latest reference-body fit, reported with morph state.
    std::string reference_refit_report;
};

struct MeshEditorApplyState;
void mesh_editor_add_morph_history_candidates(const MeshEditorSession&, std::set<int>&);
void mesh_editor_capture_morph_before_apply(MeshEditorSession&, MeshEditorApplyState&);

struct SparseVertexSnapshotSubmesh {
    int vertex_count = 0;
    std::vector<int> vertex_indices;
    std::vector<Vec3> positions;
};

std::map<std::string, std::map<int, MeshSessionSubmesh>> g_mesh_sessions;
std::map<std::string, std::map<int, MeshSessionSubmesh>> g_mesh_snapshots;
std::map<std::string, std::map<int, SparseVertexSnapshotSubmesh>> g_sparse_vertex_snapshots;
std::map<std::string, MeshEditorSession> g_mesh_editor_sessions;

constexpr std::size_t MESH_EDITOR_HISTORY_MAX_OPERATIONS = 64;
constexpr std::size_t MESH_EDITOR_HISTORY_MAX_BYTES = 256ULL * 1024ULL * 1024ULL;

// How many bones may drive one vertex. A PAC vertex record holds six influences, and real
// bodies use every one, so blending down to four here would throw away weights the file can
// carry. Mirrors PAC_SKIN_INFLUENCES on the Python side.
constexpr std::size_t MESH_MAX_SKIN_INFLUENCES = 6;

// The host's PAC source descriptor for a Part, carried opaquely in extra_attrs
// (NATIVE_SOURCE_DESCRIPTOR_ATTR on the Python side).
constexpr const char* MESH_EDITOR_SOURCE_DESCRIPTOR_ATTR = "_cdmw_source_descriptor";

std::map<int, MeshSessionSubmesh>& mesh_editor_submeshes(MeshEditorSession& session) {
    const auto found = g_mesh_sessions.find(session.native_session_id);
    if (found == g_mesh_sessions.end()) {
        throw std::runtime_error("missing mesh editor native session");
    }
    return found->second;
}

const std::map<int, MeshSessionSubmesh>& mesh_editor_submeshes(const MeshEditorSession& session) {
    const auto found = g_mesh_sessions.find(session.native_session_id);
    if (found == g_mesh_sessions.end()) {
        throw std::runtime_error("missing mesh editor native session");
    }
    return found->second;
}

std::size_t mesh_editor_history_stack_retained_bytes(const std::vector<MeshEditorHistoryEntry>& stack);
std::array<std::size_t, 2> mesh_editor_session_history_retained_bytes(const MeshEditorSession& session);

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open input file: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}
