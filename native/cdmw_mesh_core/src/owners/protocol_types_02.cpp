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

struct MeshEditorHistoryEntry {
    // Topology units retain one reversible affected-submesh snapshot. Applying
    // the unit swaps current state back into this map for redo.
    std::map<int, MeshSessionSubmesh> before;
    std::map<int, MeshEditorSubmeshDelta> deltas;
    std::set<int> absent_before;
    std::map<int, int> append_source_indices;
    std::string operation;
    std::string stroke_id;
    int stroke_update_count = 0;
    bool topology_changed = false;
};

struct MeshEditorStroke {
    bool active = false;
    std::string stroke_id;
    std::string operation;
    std::string tool;
    int update_count = 0;
};

struct MeshEditorSession {
    std::string native_session_id;
    MeshEditorSelection selection;
    MeshEditorStroke active_stroke;
    std::vector<MeshEditorHistoryEntry> undo_stack;
    std::vector<MeshEditorHistoryEntry> redo_stack;
    int topology_revision = 0;
    int selection_revision = 0;
    int edit_revision = 0;
    int stroke_revision = 0;
};

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

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open input file: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}
