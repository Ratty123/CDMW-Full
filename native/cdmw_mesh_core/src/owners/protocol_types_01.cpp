struct JsonValue {
    enum class Type { Null, Bool, Number, String, Array, Object };

    Type type = Type::Null;
    bool bool_value = false;
    double number_value = 0.0;
    std::string string_value;
    std::vector<JsonValue> array_value;
    std::map<std::string, JsonValue> object_value;

    const JsonValue* get(const std::string& key) const {
        if (type != Type::Object) {
            return nullptr;
        }
        const auto found = object_value.find(key);
        return found == object_value.end() ? nullptr : &found->second;
    }
};

class JsonParser {
public:
    explicit JsonParser(std::string text) : text_(std::move(text)) {}

    JsonValue parse() {
        if (text_.size() >= 3
            && static_cast<unsigned char>(text_[0]) == 0xEF
            && static_cast<unsigned char>(text_[1]) == 0xBB
            && static_cast<unsigned char>(text_[2]) == 0xBF) {
            pos_ = 3;
        }
        JsonValue value = parse_value();
        skip_ws();
        if (pos_ != text_.size()) {
            throw std::runtime_error("trailing JSON data");
        }
        return value;
    }

private:
    JsonValue parse_value() {
        skip_ws();
        if (pos_ >= text_.size()) {
            throw std::runtime_error("unexpected end of JSON");
        }
        const char ch = text_[pos_];
        if (ch == '{') {
            return parse_object();
        }
        if (ch == '[') {
            return parse_array();
        }
        if (ch == '"') {
            JsonValue value;
            value.type = JsonValue::Type::String;
            value.string_value = parse_string();
            return value;
        }
        if (ch == '-' || (ch >= '0' && ch <= '9')) {
            return parse_number();
        }
        if (consume_literal("true")) {
            JsonValue value;
            value.type = JsonValue::Type::Bool;
            value.bool_value = true;
            return value;
        }
        if (consume_literal("false")) {
            JsonValue value;
            value.type = JsonValue::Type::Bool;
            value.bool_value = false;
            return value;
        }
        if (consume_literal("null")) {
            return JsonValue{};
        }
        throw std::runtime_error("invalid JSON value");
    }

    JsonValue parse_object() {
        expect('{');
        JsonValue value;
        value.type = JsonValue::Type::Object;
        skip_ws();
        if (try_consume('}')) {
            return value;
        }
        while (true) {
            skip_ws();
            if (pos_ >= text_.size() || text_[pos_] != '"') {
                throw std::runtime_error("object key must be a string");
            }
            std::string key = parse_string();
            skip_ws();
            expect(':');
            value.object_value.emplace(std::move(key), parse_value());
            skip_ws();
            if (try_consume('}')) {
                break;
            }
            expect(',');
        }
        return value;
    }

    JsonValue parse_array() {
        expect('[');
        JsonValue value;
        value.type = JsonValue::Type::Array;
        skip_ws();
        if (try_consume(']')) {
            return value;
        }
        while (true) {
            value.array_value.push_back(parse_value());
            skip_ws();
            if (try_consume(']')) {
                break;
            }
            expect(',');
        }
        return value;
    }

    JsonValue parse_number() {
        const char* start = text_.c_str() + pos_;
        char* end = nullptr;
        errno = 0;
        const double number = std::strtod(start, &end);
        if (end == start || errno == ERANGE || !std::isfinite(number)) {
            throw std::runtime_error("invalid JSON number");
        }
        pos_ = static_cast<std::size_t>(end - text_.c_str());
        JsonValue value;
        value.type = JsonValue::Type::Number;
        value.number_value = number;
        return value;
    }

    std::string parse_string() {
        expect('"');
        std::string result;
        while (pos_ < text_.size()) {
            const char ch = text_[pos_++];
            if (ch == '"') {
                return result;
            }
            if (ch != '\\') {
                result.push_back(ch);
                continue;
            }
            if (pos_ >= text_.size()) {
                throw std::runtime_error("unterminated JSON escape");
            }
            const char escaped = text_[pos_++];
            switch (escaped) {
            case '"':
            case '\\':
            case '/':
                result.push_back(escaped);
                break;
            case 'b':
                result.push_back('\b');
                break;
            case 'f':
                result.push_back('\f');
                break;
            case 'n':
                result.push_back('\n');
                break;
            case 'r':
                result.push_back('\r');
                break;
            case 't':
                result.push_back('\t');
                break;
            case 'u':
                if (pos_ + 4 > text_.size()) {
                    throw std::runtime_error("short JSON unicode escape");
                }
                result.push_back('?');
                pos_ += 4;
                break;
            default:
                throw std::runtime_error("invalid JSON escape");
            }
        }
        throw std::runtime_error("unterminated JSON string");
    }

    void skip_ws() {
        while (pos_ < text_.size()) {
            const char ch = text_[pos_];
            if (ch != ' ' && ch != '\t' && ch != '\r' && ch != '\n') {
                break;
            }
            ++pos_;
        }
    }

    bool try_consume(char expected) {
        if (pos_ < text_.size() && text_[pos_] == expected) {
            ++pos_;
            return true;
        }
        return false;
    }

    void expect(char expected) {
        if (!try_consume(expected)) {
            throw std::runtime_error(std::string("expected '") + expected + "'");
        }
    }

    bool consume_literal(const char* literal) {
        const std::string needle(literal);
        if (text_.compare(pos_, needle.size(), needle) != 0) {
            return false;
        }
        pos_ += needle.size();
        return true;
    }

    std::string text_;
    std::size_t pos_ = 0;
};

using Vec2 = std::array<double, 2>;
using Vec3 = std::array<double, 3>;

struct Transform {
    Vec3 translate{0.0, 0.0, 0.0};
    Vec3 scale{1.0, 1.0, 1.0};
    Vec3 rotate{0.0, 0.0, 0.0};
    Vec3 pivot{0.0, 0.0, 0.0};
    std::string axis;
    double snap = 0.0;
    bool mirror_x = false;
    bool pivot_from_selection = false;
    bool recompute_normals = true;
};

struct UvTransform {
    Vec2 offset{0.0, 0.0};
    Vec2 scale{1.0, 1.0};
    double rotate = 0.0;
    bool flip_u = false;
    bool flip_v = false;
    Vec2 pivot{0.0, 0.0};
    bool validate_input_bounds = false;
    Vec2 input_bounds_min{-1.0e300, -1.0e300};
    Vec2 input_bounds_max{1.0e300, 1.0e300};
    bool clamp_input_uv = false;
    Vec2 input_clamp_min{0.0, 0.0};
    Vec2 input_clamp_max{1.0, 1.0};
    std::string projection;
    std::string plane{"xy"};
    std::string axis{"z"};
    bool initialize_missing_uvs = false;
    bool normalize = false;
    Vec2 target_min{0.0, 0.0};
    Vec2 target_max{1.0, 1.0};
    bool uv_island = false;
    bool pack = false;
    int pack_columns = 0;
    double pack_padding = 0.02;
    bool snap = false;
    Vec2 snap_step{0.0, 0.0};
    bool has_align_u = false;
    bool align_u_is_number = false;
    double align_u_number = 0.0;
    std::string align_u_mode;
    bool has_align_v = false;
    bool align_v_is_number = false;
    double align_v_number = 0.0;
    std::string align_v_mode;
};

struct SubmeshTransformResult {
    int index = -1;
    std::vector<Vec3> vertices;
    std::vector<int> source_vertex_map;
    std::vector<int> changed_source_vertex_ids;
    std::vector<int> changed_vertices;
    std::vector<Vec3> changed_positions;
    std::vector<Vec3> before_positions;
    std::string sparse_snapshot_id;
    std::string changed_vertices_path;
    std::string changed_positions_path;
    std::string before_positions_path;
    bool sparse = false;
    bool resident_sparse = false;
};

struct SubmeshSelectionResult {
    int index = -1;
    std::string selected_vertices_path;
    std::vector<int> selected_vertices;
};

struct SubmeshUvSelectionResult {
    int index = -1;
    std::string selected_vertices_path;
    std::vector<int> selected_vertices;
};

struct UvIslandSummaryResult {
    int index = -1;
    int submesh_index = -1;
    std::string part_name;
    std::string material;
    std::string texture;
    int vertex_count = 0;
    int face_count = 0;
    Vec2 uv_min{0.0, 0.0};
    Vec2 uv_max{0.0, 0.0};
    bool selected = false;
    int selected_vertex_count = 0;
    int selected_face_count = 0;
};

struct SubmeshMetadataResult {
    int index = -1;
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    bool has_uvs = false;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
};

struct SubmeshSelectionBoundsResult {
    int index = -1;
    std::size_t selected_vertex_count = 0;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
};

struct SubmeshRegionVolumeDeltaResult {
    int index = -1;
    std::vector<Vec3> deltas;
    std::string deltas_path;
    int vertex_count = 0;
    int selected_vertex_count = 0;
    int weighted_vertex_count = 0;
};

struct SubmeshSelectionPreviewResult {
    int index = -1;
    std::vector<int> source_vertex_indices;
    std::vector<int> source_face_indices;
    std::vector<std::array<int, 2>> source_edges;
    std::string selection_preview_path;
};

struct SubmeshSelectionPruneResult {
    int index = -1;
    std::vector<int> selected_vertices;
    std::vector<std::array<int, 2>> selected_edges;
    std::vector<int> selected_faces;
    std::string selected_vertices_path;
    std::string selected_edges_path;
    std::string selected_faces_path;
};

struct SubmeshUvTransformResult {
    int index = -1;
    std::string status = "ok";
    std::string error;
    int invalid_vertex_index = -1;
    Vec2 invalid_uv{0.0, 0.0};
    std::string uvs_path;
    std::string changed_vertices_path;
    std::string preview_vertex_path;
    std::vector<Vec3> vertices;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<int> changed_vertices;
    bool clear_uvs = false;
};

struct BoneAssignments {
    std::vector<std::vector<int>> indices;
    std::vector<std::vector<double>> weights;
};

struct SubmeshPreviewDecimateResult {
    int index = -1;
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    BoneAssignments bones;
    std::vector<int> source_vertex_map;
    std::string vertices_path;
    std::string faces_path;
    std::string uvs_path;
    std::string normals_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    std::string source_vertex_map_path;
};

struct SubmeshAutoUvResult {
    int index = -1;
    std::string status = "ok";
    std::string error;
    std::vector<Vec2> uvs;
    std::vector<std::array<int, 3>> faces;
    std::vector<int> vertex_remap;
    std::vector<Vec3> vertices;
    std::vector<Vec3> normals;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    BoneAssignments bones;
    std::vector<int> source_vertex_map;
    std::vector<int> source_vertex_offsets;
    std::string vertices_path;
    std::string uvs_path;
    std::string faces_path;
    std::string vertex_remap_path;
    std::string changed_vertices_path;
    std::string normals_path;
    std::string tangents_path;
    std::string tangent_signs_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    std::string source_vertex_map_path;
    std::string source_vertex_offsets_path;
    int input_vertex_count = 0;
    int output_vertex_count = 0;
    int input_face_count = 0;
    int output_face_count = 0;
    int chart_count = 0;
    bool topology_changed = false;
    std::vector<int> changed_vertices;
};

struct SubmeshNormalsResult {
    int index = -1;
    std::string normals_path;
    std::string faces_path;
    std::string changed_vertices_path;
    std::string preview_vertex_path;
    std::string preview_triangle_path;
    std::vector<Vec3> vertices;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<std::array<int, 3>> faces;
    std::vector<int> source_vertex_map;
    std::vector<int> changed_vertices;
};

struct SubmeshMorphApplyResult {
    int index = -1;
    std::string vertices_path;
    std::string normals_path;
    int vertex_count = 0;
    int normal_count = 0;
};

struct SubmeshMorphPostEditDeltaResult {
    int index = -1;
    std::vector<Vec3> deltas;
    std::string deltas_path;
    int vertex_count = 0;
    bool zero_delta = false;
};

struct SubmeshStaticDonorIndicesResult {
    int index = -1;
    int original_vertex_count = 0;
    int new_vertex_count = 0;
    std::vector<int> donor_indices;
    std::string donor_indices_path;
    bool sequence_alignment_used = false;
    bool sequence_alignment_fallback = false;
};

struct SubmeshSkinWeightsResult {
    int index = -1;
    int vertex_count = 0;
    std::vector<int> changed_vertices;
    BoneAssignments bones;
    std::string changed_vertices_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    double transfer_distance_p95 = 0.0;
    double transfer_distance_limit = 0.0;
    bool transfer_distance_warning = false;
};

struct NativePoseBone {
    int index = -1;
    int parent_index = -1;
    Vec3 position{0.0, 0.0, 0.0};
    std::array<double, 16> bind_matrix{};
    std::array<double, 16> inv_bind_matrix{};
    bool has_bind_matrix = false;
    bool has_inv_bind_matrix = false;
};

struct SubmeshPosePreviewResult {
    int index = -1;
    int vertex_count = 0;
    std::vector<int> changed_vertices;
    std::vector<Vec3> vertices;
    std::string vertices_path;
    std::string changed_vertices_path;
};

struct ObjExportResult {
    std::string output_path;
    std::string manifest_path;
    int submesh_count = 0;
    int vertex_count = 0;
    int face_count = 0;
};

struct ObjRoundtripManifestSubmesh {
    int index = -1;
    std::string name;
    std::string material;
    std::string texture;
    int vertex_count = 0;
    int face_count = 0;
    std::vector<int> source_vertex_map;
};

struct ObjManifestResult {
    std::string manifest_path;
    int submesh_count = 0;
    int vertex_count = 0;
    int face_count = 0;
};

struct FbxGeometrySubmeshResult {
    int index = -1;
    int vertex_count = 0;
    int face_count = 0;
    int normal_count = 0;
    int uv_count = 0;
    std::string vertices_path;
    std::string indices_path;
    std::string normals_path;
    std::string uvs_path;
    std::size_t vertex_value_count = 0;
    std::size_t index_value_count = 0;
    std::size_t normal_value_count = 0;
    std::size_t uv_value_count = 0;
};

struct FbxExportResult {
    std::string output_path;
    int submesh_count = 0;
    int vertex_count = 0;
    int face_count = 0;
};

struct FaceCornerTangents {
    int face_index = -1;
    std::array<int, 3> vertices{0, 0, 0};
    std::array<Vec3, 3> tangents{Vec3{1.0, 0.0, 0.0}, Vec3{1.0, 0.0, 0.0}, Vec3{1.0, 0.0, 0.0}};
    std::array<double, 3> signs{1.0, 1.0, 1.0};
};

struct SubmeshTangentsResult {
    int index = -1;
    std::string vertices_path;
    std::string faces_path;
    std::string normals_path;
    std::string uvs_path;
    std::string tangents_path;
    std::string tangent_signs_path;
    std::string changed_vertices_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    std::string source_vertex_map_path;
    std::string source_vertex_offsets_path;
    std::string tangent_backend = "cdmw_fallback";
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    BoneAssignments bones;
    std::vector<int> source_vertex_map;
    std::vector<int> source_vertex_offsets;
    std::vector<int> changed_vertices;
    std::vector<FaceCornerTangents> face_corner_tangents;
    std::vector<int> split_required_vertices;
    int face_corner_tangent_count = 0;
    int degenerate_uv_faces = 0;
    bool vertex_storage_safe = true;
    bool topology_split_applied = false;
    bool clear_tangents = false;
};

struct TangentBuildResult {
    std::string tangent_backend = "cdmw_fallback";
    std::vector<Vec3> vertex_tangents;
    std::vector<double> vertex_signs;
    std::vector<FaceCornerTangents> face_corner_tangents;
    std::vector<int> split_required_vertices;
    int face_corner_tangent_count = 0;
    int degenerate_uv_faces = 0;
    bool vertex_storage_safe = true;
};

struct SubmeshCleanupResult {
    int index = -1;
    std::string vertices_path;
    std::string faces_path;
    std::string index_map_path;
    std::string normals_path;
    std::string uvs_path;
    std::string tangents_path;
    std::string tangent_signs_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    std::string source_vertex_map_path;
    std::string source_vertex_offsets_path;
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<int> index_map;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    BoneAssignments bones;
    std::vector<int> source_vertex_map;
    std::vector<int> source_vertex_offsets;
    int removed_vertices = 0;
    int removed_faces = 0;
    int merged_vertices = 0;
    int degenerate_faces = 0;
    int duplicate_faces = 0;
    bool suppress_index_map_report = false;
};

struct OptimizationStats {
    double cache_acmr = 0.0;
    double cache_atvr = 0.0;
    double overdraw = 0.0;
    double overfetch = 0.0;
};

struct SubmeshOptimizeResult {
    int index = -1;
    std::vector<std::array<int, 3>> faces;
    int input_vertex_count = 0;
    int input_index_count = 0;
    int input_triangle_count = 0;
    int output_index_count = 0;
    int output_triangle_count = 0;
    int referenced_vertex_count = 0;
    int fetch_vertex_count = 0;
    double target_ratio = 1.0;
    double target_error = 0.01;
    double result_error = 0.0;
    bool simplified = false;
    bool topology_changed = false;
    OptimizationStats before;
    OptimizationStats after;
};

struct VertexBlend {
    int index = -1;
    int left = -1;
    int right = -1;
    double factor = 0.5;
};

struct SubmeshMeshEditResult {
    int index = -1;
    std::string action;
    bool append_submesh = false;
    int source_index = -1;
    std::string name_suffix;
    std::string name;
    std::string material;
    std::string texture;
    JsonValue extra_attrs;
    bool material_metadata_changed = false;
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<Vec3> normals;
    std::vector<Vec3> preview_normals;
    std::vector<Vec2> preview_uvs;
    std::vector<int> changed_vertices;
    std::vector<Vec3> changed_positions;
    std::vector<Vec3> before_positions;
    std::string sparse_snapshot_id;
    std::string changed_vertices_path;
    std::string changed_positions_path;
    std::string before_positions_path;
    std::string vertices_path;
    std::string faces_path;
    std::string normals_path;
    std::string uvs_path;
    std::string tangents_path;
    std::string tangent_signs_path;
    std::string bone_counts_path;
    std::string bone_indices_path;
    std::string bone_weights_path;
    std::string source_vertex_map_path;
    std::string source_vertex_offsets_path;
    std::string preview_triangle_path;
    std::vector<int> source_vertex_map;
    std::vector<int> changed_source_vertex_ids;
    std::vector<int> source_vertex_offsets;
    std::vector<int> source_face_indices;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    BoneAssignments bones;
    std::string copy_vertex_indices_path;
    std::string vertex_blend_indices_path;
    std::string vertex_blend_factors_path;
    std::string index_map_path;
    std::vector<int> copy_vertex_indices;
    std::vector<VertexBlend> vertex_blends;
    std::vector<int> index_map;
    int removed_faces = 0;
    int removed_vertices = 0;
    int added_vertices = 0;
    int added_faces = 0;
    int mirror_axis_index = -1;
    bool topology_changed = false;
    bool sparse = false;
    bool resident_sparse = false;
    bool suppress_vertex_remap_report = false;
};

struct MeshSessionSubmesh {
    std::string name;
    std::string material;
    std::string texture;
    JsonValue extra_attrs;
    std::vector<Vec3> vertices;
    std::vector<std::array<int, 3>> faces;
    std::vector<int> source_face_indices;
    std::vector<Vec3> normals;
    std::vector<Vec2> uvs;
    std::vector<Vec3> tangents;
    std::vector<double> tangent_signs;
    std::vector<std::vector<int>> bone_indices;
    std::vector<std::vector<double>> bone_weights;
    std::vector<int> source_vertex_map;
    std::vector<int> source_vertex_offsets;
};

bool mesh_editor_same_material_metadata(const MeshSessionSubmesh& left, const MeshSessionSubmesh& right);

struct MeshEditorSelection {
    std::map<int, std::set<int>> vertices;
    std::map<int, std::map<int, double>> vertex_weights;
    std::map<int, std::set<int>> faces;
    std::map<int, std::set<std::array<int, 2>>> edges;
    std::set<int> source_indices;
};

template <typename T>
struct MeshEditorChannelDelta {
    std::size_t before_size = 0;
    std::size_t after_size = 0;
    std::vector<int> indices;
    std::vector<T> before_values;
    std::vector<T> after_values;
    std::vector<T> before_replacement;
    std::vector<T> after_replacement;
    bool replacement = false;
};
