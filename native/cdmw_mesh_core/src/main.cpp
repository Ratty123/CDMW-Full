#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#include "meshoptimizer.h"
#include "mikktspace.h"
#include "ufbx.h"
#include "xatlas.h"

namespace {

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
    std::vector<int> changed_vertices;
    std::vector<Vec3> changed_positions;
    std::vector<Vec3> before_positions;
    std::string sparse_snapshot_id;
    std::string changed_vertices_path;
    std::string changed_positions_path;
    std::string before_positions_path;
    bool sparse = false;
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

struct MeshEditorHistoryEntry {
    std::map<int, MeshSessionSubmesh> before;
    std::map<int, MeshSessionSubmesh> after;
    std::set<int> absent_before;
    std::set<int> absent_after;
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
    std::map<int, MeshSessionSubmesh> submeshes;
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

std::string read_text_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("cannot open input file: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

void write_text_file(const std::string& path, const std::string& text) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    output << text;
}

void write_escaped(std::ostream& out, const std::string& text);
void write_json_value(std::ostream& out, const JsonValue& value);

void write_binary_file(const std::string& path, const std::vector<char>& data, bool append) {
    std::ofstream output(path, std::ios::binary | (append ? std::ios::app : std::ios::trunc));
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!data.empty()) {
        output.write(data.data(), static_cast<std::streamsize>(data.size()));
    }
}

void write_vec3_binary_file(const std::string& path, const std::vector<Vec3>& values) {
    static_assert(sizeof(Vec3) == sizeof(double) * 3, "Vec3 binary layout changed");
    if (path.empty()) {
        throw std::runtime_error("missing vec3 output path");
    }
    for (const Vec3& value : values) {
        if (!std::isfinite(value[0]) || !std::isfinite(value[1]) || !std::isfinite(value[2])) {
            throw std::runtime_error("non-finite vec3 output value: " + path);
        }
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(Vec3))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write vec3 output file: " + path);
    }
}

void write_vec2_binary_file(const std::string& path, const std::vector<Vec2>& values) {
    static_assert(sizeof(Vec2) == sizeof(double) * 2, "Vec2 binary layout changed");
    if (path.empty()) {
        throw std::runtime_error("missing vec2 output path");
    }
    for (const Vec2& value : values) {
        if (!std::isfinite(value[0]) || !std::isfinite(value[1])) {
            throw std::runtime_error("non-finite vec2 output value: " + path);
        }
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(Vec2))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write vec2 output file: " + path);
    }
}

void write_double_binary_file(const std::string& path, const std::vector<double>& values) {
    if (path.empty()) {
        throw std::runtime_error("missing f64 output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (!values.empty()) {
        output.write(
            reinterpret_cast<const char*>(values.data()),
            static_cast<std::streamsize>(values.size() * sizeof(double))
        );
    }
    if (!output) {
        throw std::runtime_error("cannot write f64 output file: " + path);
    }
}

void write_int_binary_file(const std::string& path, const std::vector<int>& values) {
    if (path.empty()) {
        throw std::runtime_error("missing int output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (sizeof(int) == sizeof(std::int32_t)) {
        if (!values.empty()) {
            output.write(
                reinterpret_cast<const char*>(values.data()),
                static_cast<std::streamsize>(values.size() * sizeof(std::int32_t))
            );
        }
        if (!output) {
            throw std::runtime_error("cannot write int output file: " + path);
        }
        return;
    }
    for (const int value : values) {
        const std::int32_t raw = static_cast<std::int32_t>(value);
        output.write(reinterpret_cast<const char*>(&raw), static_cast<std::streamsize>(sizeof(raw)));
        if (!output) {
            throw std::runtime_error("cannot write int output file: " + path);
        }
    }
}

void write_faces_binary_file(const std::string& path, const std::vector<std::array<int, 3>>& faces) {
    if (path.empty()) {
        throw std::runtime_error("missing face output path");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        throw std::runtime_error("cannot open output file: " + path);
    }
    if (sizeof(std::array<int, 3>) == sizeof(std::int32_t) * 3) {
        if (!faces.empty()) {
            output.write(
                reinterpret_cast<const char*>(faces.data()),
                static_cast<std::streamsize>(faces.size() * sizeof(std::array<int, 3>))
            );
        }
        if (!output) {
            throw std::runtime_error("cannot write face output file: " + path);
        }
        return;
    }
    for (const auto& face : faces) {
        const std::int32_t raw[3] = {
            static_cast<std::int32_t>(face[0]),
            static_cast<std::int32_t>(face[1]),
            static_cast<std::int32_t>(face[2]),
        };
        output.write(reinterpret_cast<const char*>(raw), static_cast<std::streamsize>(sizeof(raw)));
        if (!output) {
            throw std::runtime_error("cannot write face output file: " + path);
        }
    }
}

double number_or(const JsonValue* value, double fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Number || !std::isfinite(value->number_value)) {
        return fallback;
    }
    return value->number_value;
}

int int_or(const JsonValue* value, int fallback) {
    const double number = number_or(value, static_cast<double>(fallback));
    if (number < static_cast<double>(INT_MIN) || number > static_cast<double>(INT_MAX)) {
        return fallback;
    }
    return static_cast<int>(number);
}

bool strict_int_or(const JsonValue* value, int& out) {
    if (value == nullptr || value->type != JsonValue::Type::Number || !std::isfinite(value->number_value)) {
        return false;
    }
    if (std::floor(value->number_value) != value->number_value
        || value->number_value < static_cast<double>(INT_MIN)
        || value->number_value > static_cast<double>(INT_MAX)) {
        return false;
    }
    out = static_cast<int>(value->number_value);
    return true;
}

bool bool_or(const JsonValue* value, bool fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Bool) {
        return fallback;
    }
    return value->bool_value;
}

std::string string_or(const JsonValue* value, const std::string& fallback = std::string()) {
    if (value == nullptr || value->type != JsonValue::Type::String) {
        return fallback;
    }
    return value->string_value;
}

std::string lower_ascii(std::string value);

void uv_align_from_json(
    const JsonValue* value,
    bool& has_value,
    bool& is_number,
    double& number,
    std::string& mode
) {
    has_value = false;
    is_number = false;
    number = 0.0;
    mode.clear();
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Number && std::isfinite(value->number_value)) {
        has_value = true;
        is_number = true;
        number = value->number_value;
        return;
    }
    if (value->type == JsonValue::Type::String) {
        has_value = true;
        mode = lower_ascii(value->string_value);
    }
}

std::vector<Vec3> vertices_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<Vec2> uvs_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<std::array<int, 3>> faces_from_binary_or_json_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t vertex_count
);
std::vector<std::array<int, 3>> faces_from_binary_or_json(const JsonValue& item, std::size_t vertex_count);
std::vector<int> int_vector_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string(),
    const std::string& range_stride_key = std::string()
);
std::vector<double> double_vector_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key);
std::vector<Vec3> compute_smooth_normals(const std::vector<Vec3>& vertices, const std::vector<std::array<int, 3>>& faces);
bool valid_bone_assignments(const BoneAssignments& bones);

const MeshSessionSubmesh* mesh_session_submesh_for_item(const JsonValue& item) {
    const std::string session_id = string_or(item.get("session_id"), "");
    const int submesh_index = int_or(item.get("index"), -1);
    if (session_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    const auto session_found = g_mesh_sessions.find(session_id);
    if (session_found == g_mesh_sessions.end()) {
        return nullptr;
    }
    const auto submesh_found = session_found->second.find(submesh_index);
    return submesh_found == session_found->second.end() ? nullptr : &submesh_found->second;
}

MeshSessionSubmesh* mutable_mesh_session_submesh_for_item(const JsonValue& item) {
    const std::string session_id = string_or(item.get("session_id"), "");
    const int submesh_index = int_or(item.get("index"), -1);
    if (session_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    auto session_found = g_mesh_sessions.find(session_id);
    if (session_found == g_mesh_sessions.end()) {
        return nullptr;
    }
    auto submesh_found = session_found->second.find(submesh_index);
    return submesh_found == session_found->second.end() ? nullptr : &submesh_found->second;
}

const MeshSessionSubmesh* mesh_snapshot_submesh_for_item(const std::string& snapshot_id, const JsonValue& item) {
    const int submesh_index = int_or(item.get("index"), -1);
    if (snapshot_id.empty() || submesh_index < 0) {
        return nullptr;
    }
    const auto snapshot_found = g_mesh_snapshots.find(snapshot_id);
    if (snapshot_found == g_mesh_snapshots.end()) {
        return nullptr;
    }
    const auto submesh_found = snapshot_found->second.find(submesh_index);
    return submesh_found == snapshot_found->second.end() ? nullptr : &submesh_found->second;
}

bool item_has_direct_geometry(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    return item.get(binary_key) != nullptr || item.get(json_key) != nullptr;
}

std::vector<Vec3> mesh_vertices_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "vertices_binary", "vertices")) {
        return vertices_from_binary_or_json(item, "vertices_binary", "vertices");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->vertices;
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session vertices");
    }
    return {};
}

std::size_t mesh_vertex_count_from_item(const JsonValue& item) {
    const int explicit_count = int_or(item.get("vertex_count"), -1);
    if (explicit_count >= 0) {
        return static_cast<std::size_t>(explicit_count);
    }
    if (item_has_direct_geometry(item, "vertices_binary", "vertices")) {
        return vertices_from_binary_or_json(item, "vertices_binary", "vertices").size();
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->vertices.size();
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session vertex count");
    }
    return 0;
}

std::vector<std::array<int, 3>> mesh_faces_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("faces_binary") != nullptr || item.get("faces") != nullptr) {
        return faces_from_binary_or_json(item, vertex_count);
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->vertices.size() == vertex_count) {
            return session->faces;
        }
        return {};
    }
    if (!string_or(item.get("session_id"), "").empty()) {
        throw std::runtime_error("missing native mesh session faces");
    }
    return {};
}

std::vector<int> identity_indices(std::size_t count) {
    std::vector<int> result;
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        result.push_back(static_cast<int>(index));
    }
    return result;
}

bool contiguous_int_range(const std::vector<int>& values, int& start) {
    if (values.empty()) {
        return false;
    }
    start = values.front();
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (values[index] != start + static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

bool contiguous_int_stride_range(const std::vector<int>& values, int& start, int& stride) {
    if (values.empty()) {
        return false;
    }
    start = values.front();
    if (values.size() == 1) {
        stride = 1;
        return true;
    }
    stride = values[1] - values[0];
    if (stride <= 0) {
        return false;
    }
    for (std::size_t index = 0; index < values.size(); ++index) {
        const long long expected = static_cast<long long>(start)
            + static_cast<long long>(index) * static_cast<long long>(stride);
        if (expected < static_cast<long long>(INT_MIN)
            || expected > static_cast<long long>(INT_MAX)
            || values[index] != static_cast<int>(expected)) {
            return false;
        }
    }
    return true;
}

std::vector<int> int_vector_from_range_fields(
    const JsonValue& item,
    const std::string& range_start_key,
    const std::string& range_count_key,
    const std::string& range_stride_key = std::string()
) {
    std::vector<int> result;
    if (range_start_key.empty() || range_count_key.empty()) {
        return result;
    }
    const int start = int_or(item.get(range_start_key), -1);
    const int count = int_or(item.get(range_count_key), 0);
    const int stride = range_stride_key.empty() ? 1 : int_or(item.get(range_stride_key), 1);
    if (start < 0 || count <= 0) {
        return result;
    }
    if (stride == 0) {
        return result;
    }
    result.reserve(static_cast<std::size_t>(count));
    for (int offset = 0; offset < count; ++offset) {
        const long long value = static_cast<long long>(start) + static_cast<long long>(offset) * static_cast<long long>(stride);
        if (value < static_cast<long long>(INT_MIN) || value > static_cast<long long>(INT_MAX)) {
            return {};
        }
        result.push_back(static_cast<int>(value));
    }
    return result;
}

std::vector<int> mesh_source_vertex_indices_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("source_vertex_indices_binary") != nullptr
        || item.get("source_vertex_indices") != nullptr
        || item.get("source_vertex_start") != nullptr) {
        std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_indices_binary",
            "source_vertex_indices",
            "source_vertex_start",
            "source_vertex_count"
        );
        if (values.size() > vertex_count) {
            values.resize(vertex_count);
        }
        return values;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return identity_indices(vertex_count);
}

std::vector<int> mesh_source_face_indices_from_item(const JsonValue& item, std::size_t face_count) {
    if (item.get("source_face_indices_binary") != nullptr
        || item.get("source_face_indices") != nullptr
        || item.get("source_face_start") != nullptr) {
        std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_face_indices_binary",
            "source_face_indices",
            "source_face_start",
            "source_face_count"
        );
        if (values.size() > face_count) {
            values.resize(face_count);
        }
        return values;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_face_indices.size() == face_count) {
            return session->source_face_indices;
        }
    }
    return identity_indices(face_count);
}

std::vector<int> mesh_source_vertex_map_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("source_vertex_map_binary") != nullptr
        || item.get("source_vertex_map") != nullptr
        || item.get("source_vertex_map_start") != nullptr) {
        const std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (values.size() == vertex_count) {
            return values;
        }
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return identity_indices(vertex_count);
}

std::vector<int> source_vertex_offsets_from_item(const JsonValue& item) {
    return int_vector_from_binary_or_json(
        item,
        "source_vertex_offsets_binary",
        "source_vertex_offsets",
        "source_vertex_offsets_start",
        "source_vertex_offsets_count",
        "source_vertex_offsets_stride"
    );
}

std::string filename_from_path(const std::string& path) {
    const std::size_t pos = path.find_last_of("/\\");
    if (pos == std::string::npos) {
        return path;
    }
    return path.substr(pos + 1);
}

std::string utc_timestamp_seconds() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t raw_time = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &raw_time);
#else
    gmtime_r(&raw_time, &utc);
#endif
    char buffer[32] = {};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return std::string(buffer);
}

std::vector<Vec3> mesh_normals_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "normals_binary", "normals")) {
        return vertices_from_binary_or_json(item, "normals_binary", "normals");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->normals;
    }
    return {};
}

std::vector<Vec2> mesh_uvs_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "uvs_binary", "uvs")) {
        return uvs_from_binary_or_json(item, "uvs_binary", "uvs");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->uvs;
    }
    return {};
}

std::vector<Vec3> mesh_tangents_from_item(const JsonValue& item) {
    if (item_has_direct_geometry(item, "tangents_binary", "tangents")) {
        return vertices_from_binary_or_json(item, "tangents_binary", "tangents");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->tangents;
    }
    return {};
}

std::vector<double> mesh_tangent_signs_from_item(const JsonValue& item) {
    if (item.get("tangent_signs_binary") != nullptr || item.get("tangent_signs") != nullptr) {
        return double_vector_from_binary_or_json(item, "tangent_signs_binary", "tangent_signs");
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return session->tangent_signs;
    }
    return {};
}

BoneAssignments bone_assignments_from_binary(const JsonValue& item) {
    BoneAssignments result;
    if (item.get("bone_counts_binary") == nullptr || item.get("bone_indices_binary") == nullptr || item.get("bone_weights_binary") == nullptr) {
        return result;
    }
    const std::vector<int> counts = int_vector_from_binary_or_json(item, "bone_counts_binary", "bone_counts");
    const std::vector<int> flat_indices = int_vector_from_binary_or_json(item, "bone_indices_binary", "bone_indices_flat");
    const std::vector<double> flat_weights = double_vector_from_binary_or_json(item, "bone_weights_binary", "bone_weights_flat");
    if (flat_indices.size() != flat_weights.size()) {
        return {};
    }
    std::size_t flat_offset = 0;
    result.indices.reserve(counts.size());
    result.weights.reserve(counts.size());
    for (const int raw_count : counts) {
        if (raw_count < 0) {
            return {};
        }
        const std::size_t count = static_cast<std::size_t>(raw_count);
        if (flat_offset + count > flat_indices.size()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        indices.reserve(count);
        weights.reserve(count);
        for (std::size_t index = 0; index < count; ++index) {
            const int bone = flat_indices[flat_offset + index];
            const double weight = flat_weights[flat_offset + index];
            if (bone < 0 || !std::isfinite(weight)) {
                return {};
            }
            indices.push_back(bone);
            weights.push_back(weight);
        }
        result.indices.push_back(std::move(indices));
        result.weights.push_back(std::move(weights));
        flat_offset += count;
    }
    if (flat_offset != flat_indices.size()) {
        return {};
    }
    return result;
}

BoneAssignments mesh_bones_from_item(const JsonValue& item) {
    BoneAssignments direct = bone_assignments_from_binary(item);
    if (!direct.indices.empty() || item.get("bone_counts_binary") != nullptr) {
        return direct;
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        return {session->bone_indices, session->bone_weights};
    }
    return {};
}

std::vector<int> int_vector_from_json(const JsonValue* value) {
    std::vector<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            continue;
        }
        if (item.number_value < static_cast<double>(INT_MIN) || item.number_value > static_cast<double>(INT_MAX)) {
            continue;
        }
        result.push_back(static_cast<int>(item.number_value));
    }
    return result;
}

std::vector<double> double_vector_from_json(const JsonValue* value) {
    std::vector<double> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            result.push_back(1.0);
            continue;
        }
        result.push_back(item.number_value);
    }
    return result;
}

bool matrix4x4_from_json(const JsonValue* value, std::array<double, 16>& matrix) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() != matrix.size()) {
        return false;
    }
    for (std::size_t index = 0; index < matrix.size(); ++index) {
        const JsonValue& item = value->array_value[index];
        if (item.type != JsonValue::Type::Number || !std::isfinite(item.number_value)) {
            return false;
        }
        matrix[index] = item.number_value;
    }
    return true;
}

bool matrix4x4_inverse(const std::array<double, 16>& matrix, std::array<double, 16>& inverse) {
    std::array<std::array<double, 8>, 4> work{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)] =
                matrix[static_cast<std::size_t>(row * 4 + column)];
        }
        work[static_cast<std::size_t>(row)][static_cast<std::size_t>(4 + row)] = 1.0;
    }
    for (int column = 0; column < 4; ++column) {
        int pivot = column;
        double pivot_abs = std::abs(work[static_cast<std::size_t>(pivot)][static_cast<std::size_t>(column)]);
        for (int row = column + 1; row < 4; ++row) {
            const double candidate = std::abs(work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)]);
            if (candidate > pivot_abs) {
                pivot = row;
                pivot_abs = candidate;
            }
        }
        if (!std::isfinite(pivot_abs) || pivot_abs <= 1e-12) {
            return false;
        }
        if (pivot != column) {
            std::swap(work[static_cast<std::size_t>(pivot)], work[static_cast<std::size_t>(column)]);
        }
        const double divisor = work[static_cast<std::size_t>(column)][static_cast<std::size_t>(column)];
        for (double& value : work[static_cast<std::size_t>(column)]) {
            value /= divisor;
        }
        for (int row = 0; row < 4; ++row) {
            if (row == column) {
                continue;
            }
            const double factor = work[static_cast<std::size_t>(row)][static_cast<std::size_t>(column)];
            if (std::abs(factor) <= 1e-18) {
                continue;
            }
            for (int item = 0; item < 8; ++item) {
                work[static_cast<std::size_t>(row)][static_cast<std::size_t>(item)] -=
                    factor * work[static_cast<std::size_t>(column)][static_cast<std::size_t>(item)];
            }
        }
    }
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            const double value = work[static_cast<std::size_t>(row)][static_cast<std::size_t>(4 + column)];
            if (!std::isfinite(value)) {
                return false;
            }
            inverse[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return true;
}

std::array<double, 16> matrix4x4_multiply(const std::array<double, 16>& left, const std::array<double, 16>& right) {
    std::array<double, 16> result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            double value = 0.0;
            for (int inner = 0; inner < 4; ++inner) {
                value += left[static_cast<std::size_t>(row * 4 + inner)]
                    * right[static_cast<std::size_t>(inner * 4 + column)];
            }
            result[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return result;
}

bool matrix4x4_from_transform_json(const JsonValue& item, std::array<double, 16>& matrix) {
    return matrix4x4_from_json(item.get("world_transform"), matrix)
        || matrix4x4_from_json(item.get("transform"), matrix)
        || matrix4x4_from_json(item.get("matrix"), matrix);
}

Vec3 vec3_or(const JsonValue* value, const Vec3& fallback) {
    if (value == nullptr) {
        return fallback;
    }
    if (value->type == JsonValue::Type::Object) {
        return {
            number_or(value->get("x"), fallback[0]),
            number_or(value->get("y"), fallback[1]),
            number_or(value->get("z"), fallback[2]),
        };
    }
    if (value->type != JsonValue::Type::Array || value->array_value.size() < 3) {
        return fallback;
    }
    return {
        number_or(&value->array_value[0], fallback[0]),
        number_or(&value->array_value[1], fallback[1]),
        number_or(&value->array_value[2], fallback[2]),
    };
}

Vec2 vec2_or(const JsonValue* value, const Vec2& fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() < 2) {
        return fallback;
    }
    return {
        number_or(&value->array_value[0], fallback[0]),
        number_or(&value->array_value[1], fallback[1]),
    };
}

double degrees_to_radians(double degrees) {
    return degrees * 3.14159265358979323846 / 180.0;
}

double screen_drag_axis_delta(
    const JsonValue& value,
    const std::string& short_key,
    const std::string& pixel_key,
    const std::string& start_key,
    const std::string& end_key
) {
    if (const JsonValue* delta = value.get(pixel_key)) {
        return number_or(delta, 0.0);
    }
    if (const JsonValue* delta = value.get(short_key)) {
        return number_or(delta, 0.0);
    }
    const double start = number_or(value.get(start_key), 0.0);
    return number_or(value.get(end_key), start) - start;
}

double mesh_editor_screen_units_per_pixel(const JsonValue& value) {
    double units_per_pixel = number_or(value.get("units_per_pixel"), 0.0);
    if (units_per_pixel > 0.0) {
        return units_per_pixel;
    }
    const double distance = std::max(number_or(value.get("distance"), 0.0), 0.1);
    const double viewport_height = std::max(number_or(value.get("viewport_height"), 0.0), 1.0);
    const double fov = std::max(number_or(value.get("vertical_fov_degrees"), 45.0), 1e-6);
    return (2.0 * distance * std::tan(degrees_to_radians(fov) * 0.5)) / viewport_height;
}

bool project_vertex_with_matrix_depth(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y,
    double& depth_z
) {
    const double clip_x = vertex[0] * matrix[0] + vertex[1] * matrix[4] + vertex[2] * matrix[8] + matrix[12];
    const double clip_y = vertex[0] * matrix[1] + vertex[1] * matrix[5] + vertex[2] * matrix[9] + matrix[13];
    const double clip_z = vertex[0] * matrix[2] + vertex[1] * matrix[6] + vertex[2] * matrix[10] + matrix[14];
    const double clip_w = vertex[0] * matrix[3] + vertex[1] * matrix[7] + vertex[2] * matrix[11] + matrix[15];
    if (!std::isfinite(clip_x) || !std::isfinite(clip_y) || !std::isfinite(clip_z) || !std::isfinite(clip_w)) {
        return false;
    }
    if (std::abs(clip_w) <= 1e-12) {
        return false;
    }
    const double ndc_x = clip_x / clip_w;
    const double ndc_y = clip_y / clip_w;
    const double ndc_z = clip_z / clip_w;
    if (!std::isfinite(ndc_x) || !std::isfinite(ndc_y) || !std::isfinite(ndc_z)) {
        return false;
    }
    if (ndc_z < 0.0 || ndc_z > 1.0) {
        return false;
    }
    screen_x = viewport_x + (ndc_x * 0.5 + 0.5) * viewport_width;
    screen_y = viewport_y + (0.5 - ndc_y * 0.5) * viewport_height;
    depth_z = ndc_z;
    return std::isfinite(screen_x) && std::isfinite(screen_y) && std::isfinite(depth_z);
}

bool project_vertex_with_matrix(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y
) {
    double depth_z = 0.0;
    return project_vertex_with_matrix_depth(
        matrix,
        vertex,
        viewport_x,
        viewport_y,
        viewport_width,
        viewport_height,
        screen_x,
        screen_y,
        depth_z
    );
}

bool unproject_screen_point_with_matrix_inverse(
    const std::array<double, 16>& inverse_matrix,
    double screen_x,
    double screen_y,
    double depth_z,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    Vec3& point
) {
    if (viewport_width <= 0.0 || viewport_height <= 0.0) {
        return false;
    }
    const double ndc_x = ((screen_x - viewport_x) / viewport_width - 0.5) * 2.0;
    const double ndc_y = (0.5 - (screen_y - viewport_y) / viewport_height) * 2.0;
    const double world_x = ndc_x * inverse_matrix[0] + ndc_y * inverse_matrix[4] + depth_z * inverse_matrix[8] + inverse_matrix[12];
    const double world_y = ndc_x * inverse_matrix[1] + ndc_y * inverse_matrix[5] + depth_z * inverse_matrix[9] + inverse_matrix[13];
    const double world_z = ndc_x * inverse_matrix[2] + ndc_y * inverse_matrix[6] + depth_z * inverse_matrix[10] + inverse_matrix[14];
    const double world_w = ndc_x * inverse_matrix[3] + ndc_y * inverse_matrix[7] + depth_z * inverse_matrix[11] + inverse_matrix[15];
    if (!std::isfinite(world_x) || !std::isfinite(world_y) || !std::isfinite(world_z)
        || !std::isfinite(world_w) || std::abs(world_w) <= 1e-12) {
        return false;
    }
    point = {world_x / world_w, world_y / world_w, world_z / world_w};
    return std::isfinite(point[0]) && std::isfinite(point[1]) && std::isfinite(point[2]);
}

bool mesh_editor_screen_drag_matrix_delta(
    const JsonValue& value,
    double dx,
    double dy,
    double units_per_pixel,
    Vec3& result
) {
    std::array<double, 16> camera_world{};
    if (!matrix4x4_from_json(value.get("camera_world"), camera_world)) {
        return false;
    }
    const Vec3 right{camera_world[0], camera_world[1], camera_world[2]};
    const Vec3 up{camera_world[4], camera_world[5], camera_world[6]};
    for (const double component : {right[0], right[1], right[2], up[0], up[1], up[2]}) {
        if (!std::isfinite(component)) {
            return false;
        }
    }
    result = {
        (right[0] * dx - up[0] * dy) * units_per_pixel,
        (right[1] * dx - up[1] * dy) * units_per_pixel,
        (right[2] * dx - up[2] * dy) * units_per_pixel,
    };
    return std::isfinite(result[0]) && std::isfinite(result[1]) && std::isfinite(result[2]);
}

double mesh_editor_screen_radius_pixels(const JsonValue& value) {
    return std::max(
        0.0,
        number_or(value.get("radius_pixels"), number_or(value.get("brush_radius_pixels"), number_or(value.get("pixels"), 0.0)))
    );
}

double mesh_editor_screen_radius_units(const JsonValue* value) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double pixels = mesh_editor_screen_radius_pixels(*value);
    return pixels * mesh_editor_screen_units_per_pixel(*value);
}

int mesh_editor_source_projection_override_index(const JsonValue& item) {
    if (item.type != JsonValue::Type::Object) {
        return -1;
    }
    return int_or(
        item.get("source_submesh_index"),
        int_or(item.get("submesh_index"), int_or(item.get("index"), -1))
    );
}

bool mesh_editor_has_source_projection_override(const JsonValue* value, int source_submesh_index) {
    if (value == nullptr || value->type != JsonValue::Type::Object || source_submesh_index < 0) {
        return false;
    }
    for (const char* key : {
             "source_submesh_world_view_projections",
             "source_world_view_projections",
             "source_submesh_world_transforms",
             "source_world_transforms",
         }) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            return true;
        }
        for (const JsonValue& item : overrides->array_value) {
            if (mesh_editor_source_projection_override_index(item) == source_submesh_index) {
                return true;
            }
        }
    }
    return false;
}

bool mesh_editor_source_world_view_projection_from_json(
    const JsonValue* value,
    int source_submesh_index,
    std::array<double, 16>& world_view_projection
) {
    if (value == nullptr || value->type != JsonValue::Type::Object || source_submesh_index < 0) {
        return false;
    }
    for (const char* key : {"source_submesh_world_view_projections", "source_world_view_projections"}) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr || overrides->type != JsonValue::Type::Array) {
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int item_source = mesh_editor_source_projection_override_index(item);
            if (item_source == source_submesh_index
                && matrix4x4_from_json(item.get("world_view_projection"), world_view_projection)) {
                return true;
            }
        }
    }
    std::array<double, 16> base_world_view_projection{};
    if (!matrix4x4_from_json(value->get("world_view_projection"), base_world_view_projection)) {
        return false;
    }
    for (const char* key : {"source_submesh_world_transforms", "source_world_transforms"}) {
        const JsonValue* overrides = value->get(key);
        if (overrides == nullptr || overrides->type != JsonValue::Type::Array) {
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int item_source = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_transform{};
            if (item_source == source_submesh_index && matrix4x4_from_transform_json(item, source_world_transform)) {
                world_view_projection = matrix4x4_multiply(source_world_transform, base_world_view_projection);
                return true;
            }
        }
    }
    return false;
}

bool mesh_editor_world_view_projection_from_json(
    const JsonValue* value,
    int source_submesh_index,
    std::array<double, 16>& world_view_projection
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return false;
    }
    const bool has_base_projection = matrix4x4_from_json(value->get("world_view_projection"), world_view_projection);
    const bool has_source_projection = mesh_editor_source_world_view_projection_from_json(
        value,
        source_submesh_index,
        world_view_projection
    );
    if (has_source_projection) {
        return true;
    }
    if (mesh_editor_has_source_projection_override(value, source_submesh_index)) {
        return false;
    }
    return has_base_projection;
}

bool mesh_editor_has_projection_payload(const JsonValue* value, int source_submesh_index) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return false;
    }
    if (value->get("world_view_projection") != nullptr) {
        return true;
    }
    for (const char* key : {
             "source_submesh_world_view_projections",
             "source_world_view_projections",
             "source_submesh_world_transforms",
             "source_world_transforms",
         }) {
        if (value->get(key) != nullptr) {
            return true;
        }
    }
    return false;
}

bool mesh_editor_projection_center_depth(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index,
    std::array<double, 16>& inverse_matrix,
    double& center_x,
    double& center_y,
    double& depth_z,
    double& viewport_x,
    double& viewport_y,
    double& viewport_width,
    double& viewport_height
) {
    std::array<double, 16> world_view_projection{};
    if (!mesh_editor_world_view_projection_from_json(&value, source_submesh_index, world_view_projection)
        || !matrix4x4_inverse(world_view_projection, inverse_matrix)) {
        return false;
    }
    viewport_width = std::max(number_or(value.get("viewport_width"), number_or(value.get("width"), 0.0)), 1.0);
    viewport_height = std::max(number_or(value.get("viewport_height"), number_or(value.get("height"), 0.0)), 1.0);
    viewport_x = number_or(value.get("viewport_x"), number_or(value.get("top_left_x"), 0.0));
    viewport_y = number_or(value.get("viewport_y"), number_or(value.get("top_left_y"), 0.0));
    return project_vertex_with_matrix_depth(
        world_view_projection,
        center,
        viewport_x,
        viewport_y,
        viewport_width,
        viewport_height,
        center_x,
        center_y,
        depth_z
    );
}

double mesh_editor_screen_units_per_pixel_from_projection(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index
) {
    std::array<double, 16> inverse_matrix{};
    double center_x = 0.0;
    double center_y = 0.0;
    double depth_z = 0.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    if (!mesh_editor_projection_center_depth(
            value,
            center,
            source_submesh_index,
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height)) {
        return 0.0;
    }
    Vec3 origin{};
    Vec3 right_pixel{};
    Vec3 down_pixel{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            origin)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x + 1.0,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            right_pixel)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            center_x,
            center_y + 1.0,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            down_pixel)) {
        return 0.0;
    }
    double total = 0.0;
    int count = 0;
    for (const Vec3& point : {right_pixel, down_pixel}) {
        const double units = std::sqrt(
            (point[0] - origin[0]) * (point[0] - origin[0])
            + (point[1] - origin[1]) * (point[1] - origin[1])
            + (point[2] - origin[2]) * (point[2] - origin[2])
        );
        if (std::isfinite(units) && units > 1e-12) {
            total += units;
            ++count;
        }
    }
    return count > 0 ? total / static_cast<double>(count) : 0.0;
}

bool mesh_editor_screen_drag_projection_delta(
    const JsonValue& value,
    const Vec3& center,
    int source_submesh_index,
    Vec3& result
) {
    std::array<double, 16> inverse_matrix{};
    double center_x = 0.0;
    double center_y = 0.0;
    double depth_z = 0.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    if (!mesh_editor_projection_center_depth(
            value,
            center,
            source_submesh_index,
            inverse_matrix,
            center_x,
            center_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height)) {
        return false;
    }
    const double dx = screen_drag_axis_delta(value, "dx", "delta_x_pixels", "start_x", "end_x");
    const double dy = screen_drag_axis_delta(value, "dy", "delta_y_pixels", "start_y", "end_y");
    const double start_x = number_or(value.get("start_x"), center_x);
    const double start_y = number_or(value.get("start_y"), center_y);
    const double end_x = number_or(value.get("end_x"), start_x + dx);
    const double end_y = number_or(value.get("end_y"), start_y + dy);
    Vec3 start_point{};
    Vec3 end_point{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            start_x,
            start_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            start_point)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            end_x,
            end_y,
            depth_z,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            end_point)) {
        return false;
    }
    result = {
        end_point[0] - start_point[0],
        end_point[1] - start_point[1],
        end_point[2] - start_point[2],
    };
    return std::isfinite(result[0]) && std::isfinite(result[1]) && std::isfinite(result[2]);
}

double mesh_editor_screen_pixels_per_unit_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    std::array<double, 16> world_view_projection{};
    std::array<double, 16> camera_world{};
    const bool has_base_projection = matrix4x4_from_json(value->get("world_view_projection"), world_view_projection);
    const bool has_source_projection = mesh_editor_source_world_view_projection_from_json(
        value,
        source_submesh_index,
        world_view_projection
    );
    if ((!has_base_projection && !has_source_projection)
        || !matrix4x4_from_json(value->get("camera_world"), camera_world)) {
        return 0.0;
    }
    const double viewport_width = std::max(number_or(value->get("viewport_width"), number_or(value->get("width"), 0.0)), 1.0);
    const double viewport_height = std::max(number_or(value->get("viewport_height"), number_or(value->get("height"), 0.0)), 1.0);
    const double viewport_x = number_or(value->get("viewport_x"), number_or(value->get("top_left_x"), 0.0));
    const double viewport_y = number_or(value->get("viewport_y"), number_or(value->get("top_left_y"), 0.0));
    double center_x = 0.0;
    double center_y = 0.0;
    if (!project_vertex_with_matrix(world_view_projection, center, viewport_x, viewport_y, viewport_width, viewport_height, center_x, center_y)) {
        return 0.0;
    }
    const Vec3 right{camera_world[0], camera_world[1], camera_world[2]};
    const Vec3 up{camera_world[4], camera_world[5], camera_world[6]};
    double density_total = 0.0;
    int density_count = 0;
    auto add_density = [&](const Vec3& axis) {
        for (double component : axis) {
            if (!std::isfinite(component)) {
                return;
            }
        }
        const Vec3 endpoint{center[0] + axis[0], center[1] + axis[1], center[2] + axis[2]};
        double endpoint_x = 0.0;
        double endpoint_y = 0.0;
        if (!project_vertex_with_matrix(
                world_view_projection,
                endpoint,
                viewport_x,
                viewport_y,
                viewport_width,
                viewport_height,
                endpoint_x,
                endpoint_y)) {
            return;
        }
        const double pixels_per_unit = std::hypot(endpoint_x - center_x, endpoint_y - center_y);
        if (std::isfinite(pixels_per_unit) && pixels_per_unit > 1e-8) {
            density_total += pixels_per_unit;
            ++density_count;
        }
    };
    add_density(right);
    add_density(up);
    if (density_count <= 0) {
        return 0.0;
    }
    return density_total / static_cast<double>(density_count);
}

double mesh_editor_screen_units_per_pixel_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double explicit_units = number_or(value->get("units_per_pixel"), 0.0);
    if (explicit_units > 0.0) {
        return explicit_units;
    }
    const double projection_units = mesh_editor_screen_units_per_pixel_from_projection(*value, center, source_submesh_index);
    if (projection_units > 1e-12) {
        return projection_units;
    }
    if (mesh_editor_has_projection_payload(value, source_submesh_index)) {
        return 0.0;
    }
    const double pixels_per_unit = mesh_editor_screen_pixels_per_unit_at_center(value, center, source_submesh_index);
    if (pixels_per_unit > 1e-8) {
        return 1.0 / pixels_per_unit;
    }
    return mesh_editor_screen_units_per_pixel(*value);
}

double mesh_editor_screen_radius_units_at_center(
    const JsonValue* value,
    const Vec3& center,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return 0.0;
    }
    const double pixels = mesh_editor_screen_radius_pixels(*value);
    if (pixels <= 1e-8) {
        return 0.0;
    }
    const double units_per_pixel = mesh_editor_screen_units_per_pixel_at_center(value, center, source_submesh_index);
    if (units_per_pixel <= 1e-12) {
        return 0.0;
    }
    return pixels * units_per_pixel;
}

Vec3 mesh_editor_screen_drag_delta(
    const JsonValue* value,
    const Vec3* center = nullptr,
    int source_submesh_index = -1
) {
    if (value == nullptr || value->type != JsonValue::Type::Object) {
        return {0.0, 0.0, 0.0};
    }
    const double dx = screen_drag_axis_delta(*value, "dx", "delta_x_pixels", "start_x", "end_x");
    const double dy = screen_drag_axis_delta(*value, "dy", "delta_y_pixels", "start_y", "end_y");
    if (std::abs(dx) <= 1e-12 && std::abs(dy) <= 1e-12) {
        return {0.0, 0.0, 0.0};
    }
    if (center != nullptr) {
        Vec3 projection_delta{0.0, 0.0, 0.0};
        if (mesh_editor_screen_drag_projection_delta(*value, *center, source_submesh_index, projection_delta)) {
            return projection_delta;
        }
        if (mesh_editor_has_projection_payload(value, source_submesh_index)) {
            return {0.0, 0.0, 0.0};
        }
    }
    const double units_per_pixel = center != nullptr
        ? mesh_editor_screen_units_per_pixel_at_center(value, *center, source_submesh_index)
        : mesh_editor_screen_units_per_pixel(*value);
    Vec3 matrix_delta{0.0, 0.0, 0.0};
    if (mesh_editor_screen_drag_matrix_delta(*value, dx, dy, units_per_pixel, matrix_delta)) {
        return matrix_delta;
    }
    const double pitch = degrees_to_radians(number_or(value->get("pitch_degrees"), number_or(value->get("pitch"), 0.0)));
    const double yaw = degrees_to_radians(number_or(value->get("yaw_degrees"), number_or(value->get("yaw"), 0.0)));
    const double cp = std::cos(pitch);
    const double sp = std::sin(pitch);
    const double cy = std::cos(yaw);
    const double sy = std::sin(yaw);
    const Vec3 right{cy, sp * sy, cp * sy};
    const Vec3 up{0.0, cp, -sp};
    return {
        (right[0] * dx - up[0] * dy) * units_per_pixel,
        (right[1] * dx - up[1] * dy) * units_per_pixel,
        (right[2] * dx - up[2] * dy) * units_per_pixel,
    };
}

Vec3 add_screen_drag_delta(
    Vec3 value,
    const JsonValue* screen_drag,
    const Vec3* center = nullptr,
    int source_submesh_index = -1
) {
    const Vec3 delta = mesh_editor_screen_drag_delta(screen_drag, center, source_submesh_index);
    return {value[0] + delta[0], value[1] + delta[1], value[2] + delta[2]};
}

std::string transform_axis_constraint(const JsonValue& transform) {
    const std::string axis = lower_ascii(string_or(transform.get("axis"), string_or(transform.get("constraint_axis"), "")));
    return (axis == "x" || axis == "y" || axis == "z") ? axis : std::string();
}

Vec3 constrain_vec3_axis(Vec3 value, const std::string& axis, const Vec3& defaults) {
    if (axis.empty()) {
        return value;
    }
    return {
        axis == "x" ? value[0] : defaults[0],
        axis == "y" ? value[1] : defaults[1],
        axis == "z" ? value[2] : defaults[2],
    };
}

std::vector<Vec3> vertices_from_json(const JsonValue* value) {
    std::vector<Vec3> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            result.push_back({0.0, 0.0, 0.0});
            continue;
        }
        result.push_back({
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
            number_or(&item.array_value[2], 0.0),
        });
    }
    return result;
}

std::map<int, Vec3> indexed_vertices_from_json(const JsonValue* value, int vertex_count) {
    std::map<int, Vec3> vertices;
    if (value == nullptr || value->type != JsonValue::Type::Array || vertex_count <= 0) {
        return vertices;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int index = int_or(&item.array_value[0], -1);
        if (index < 0 || index >= vertex_count) {
            continue;
        }
        const JsonValue& position_value = item.array_value[1];
        if (position_value.type != JsonValue::Type::Array || position_value.array_value.size() < 3) {
            continue;
        }
        Vec3 position{
            number_or(&position_value.array_value[0], 0.0),
            number_or(&position_value.array_value[1], 0.0),
            number_or(&position_value.array_value[2], 0.0),
        };
        if (std::isfinite(position[0]) && std::isfinite(position[1]) && std::isfinite(position[2])) {
            vertices[index] = position;
        }
    }
    return vertices;
}

std::vector<Vec2> uvs_from_json(const JsonValue* value) {
    std::vector<Vec2> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            result.push_back({0.0, 0.0});
            continue;
        }
        result.push_back({
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
        });
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_json(const JsonValue* value, std::size_t vertex_count);

std::string binary_payload_path(const JsonValue* value) {
    if (value == nullptr) {
        return std::string();
    }
    if (value->type == JsonValue::Type::String) {
        return value->string_value;
    }
    if (value->type != JsonValue::Type::Object) {
        return std::string();
    }
    return string_or(value->get("path"), "");
}

std::vector<char> read_binary_payload(const JsonValue* value, std::size_t element_size, const std::string& label) {
    const std::string path = binary_payload_path(value);
    if (path.empty()) {
        return {};
    }
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) {
        throw std::runtime_error("cannot open binary " + label + " payload: " + path);
    }
    const std::streamoff size = input.tellg();
    if (size < 0 || (element_size > 0 && static_cast<std::uint64_t>(size) % element_size != 0)) {
        throw std::runtime_error("invalid binary " + label + " payload size");
    }
    std::vector<char> bytes(static_cast<std::size_t>(size));
    input.seekg(0, std::ios::beg);
    if (!bytes.empty() && !input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()))) {
        throw std::runtime_error("cannot read binary " + label + " payload");
    }
    return bytes;
}

std::vector<Vec3> vertices_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double) * 3, "vec3");
    std::vector<Vec3> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(double) * 3);
    std::vector<double> raw(count * 3);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Vec3 item{raw[index * 3], raw[index * 3 + 1], raw[index * 3 + 2]};
        if (!std::isfinite(item[0]) || !std::isfinite(item[1]) || !std::isfinite(item[2])) {
            throw std::runtime_error("non-finite binary vec3 payload");
        }
        result.push_back(item);
    }
    return result;
}

std::vector<int> int_vector_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(std::int32_t), "int");
    std::vector<int> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / sizeof(std::int32_t);
    std::vector<std::int32_t> raw(count);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (const std::int32_t value_item : raw) {
        result.push_back(static_cast<int>(value_item));
    }
    return result;
}

std::vector<double> double_vector_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double), "f64");
    std::vector<double> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / sizeof(double);
    result.resize(count);
    std::memcpy(result.data(), bytes.data(), bytes.size());
    for (const double item : result) {
        if (!std::isfinite(item)) {
            throw std::runtime_error("non-finite binary f64 payload");
        }
    }
    return result;
}

std::vector<double> double_vector_from_f32_or_f64_binary(const JsonValue* value) {
    const std::string kind = string_or(value != nullptr && value->type == JsonValue::Type::Object ? value->get("type") : nullptr, "f64");
    if (kind == "f32") {
        const std::vector<char> bytes = read_binary_payload(value, sizeof(float), "f32");
        std::vector<double> result;
        if (bytes.empty()) {
            return result;
        }
        const std::size_t count = bytes.size() / sizeof(float);
        std::vector<float> raw(count);
        std::memcpy(raw.data(), bytes.data(), bytes.size());
        result.reserve(count);
        for (const float item : raw) {
            if (!std::isfinite(item)) {
                throw std::runtime_error("non-finite binary f32 payload");
            }
            result.push_back(static_cast<double>(item));
        }
        return result;
    }
    return double_vector_from_binary(value);
}

std::vector<int> int_vector_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key,
    const std::string& range_count_key,
    const std::string& range_stride_key
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return int_vector_from_binary(binary);
    }
    std::vector<int> range = int_vector_from_range_fields(item, range_start_key, range_count_key, range_stride_key);
    if (!range.empty()) {
        return range;
    }
    return int_vector_from_json(item.get(json_key));
}

std::vector<double> double_vector_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return double_vector_from_binary(binary);
    }
    return double_vector_from_json(item.get(json_key));
}

std::vector<Vec2> uvs_from_binary(const JsonValue* value) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(double) * 2, "vec2");
    std::vector<Vec2> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(double) * 2);
    std::vector<double> raw(count * 2);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const Vec2 item{raw[index * 2], raw[index * 2 + 1]};
        if (!std::isfinite(item[0]) || !std::isfinite(item[1])) {
            throw std::runtime_error("non-finite binary vec2 payload");
        }
        result.push_back(item);
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_binary(const JsonValue* value, std::size_t vertex_count) {
    const std::vector<char> bytes = read_binary_payload(value, sizeof(std::int32_t) * 3, "faces");
    std::vector<std::array<int, 3>> result;
    if (bytes.empty()) {
        return result;
    }
    const std::size_t count = bytes.size() / (sizeof(std::int32_t) * 3);
    std::vector<std::int32_t> raw(count * 3);
    std::memcpy(raw.data(), bytes.data(), bytes.size());
    result.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        const int a = static_cast<int>(raw[index * 3]);
        const int b = static_cast<int>(raw[index * 3 + 1]);
        const int c = static_cast<int>(raw[index * 3 + 2]);
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            throw std::runtime_error("out-of-range binary face payload");
        }
        result.push_back({a, b, c});
    }
    return result;
}

std::vector<Vec3> vertices_from_binary_or_json(const JsonValue& item, const std::string& binary_key, const std::string& json_key) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return vertices_from_binary(binary);
    }
    return vertices_from_json(item.get(json_key));
}

std::map<int, Vec3> indexed_vertices_from_binary_or_json(const JsonValue& item, int vertex_count) {
    const JsonValue* indices_binary = item.get("vertex_indices_binary");
    const JsonValue* positions_binary = item.get("vertex_positions_binary");
    const bool has_indices = indices_binary != nullptr
        || item.get("vertex_indices") != nullptr
        || item.get("vertex_index_start") != nullptr;
    if (has_indices && positions_binary != nullptr && vertex_count > 0) {
        const std::vector<int> indices = int_vector_from_binary_or_json(
            item,
            "vertex_indices_binary",
            "vertex_indices",
            "vertex_index_start",
            "vertex_index_count"
        );
        const std::vector<Vec3> positions = vertices_from_binary(positions_binary);
        std::map<int, Vec3> result;
        const std::size_t count = std::min(indices.size(), positions.size());
        for (std::size_t offset = 0; offset < count; ++offset) {
            const int index = indices[offset];
            if (index >= 0 && index < vertex_count) {
                result[index] = positions[offset];
            }
        }
        return result;
    }
    return indexed_vertices_from_json(item.get("vertex_positions"), vertex_count);
}

std::string sparse_snapshot_id_from_root(const JsonValue& root) {
    std::string snapshot_id = string_or(root.get("native_sparse_snapshot_id"), "");
    if (snapshot_id.empty()) {
        snapshot_id = string_or(root.get("sparse_snapshot_id"), "");
    }
    return snapshot_id;
}

void store_sparse_vertex_snapshot_values(
    const std::string& snapshot_id,
    int submesh_index,
    int vertex_count,
    const std::vector<int>& vertex_indices,
    const std::vector<Vec3>& positions
) {
    if (snapshot_id.empty() || submesh_index < 0 || vertex_count <= 0 || vertex_indices.size() != positions.size()) {
        return;
    }
    SparseVertexSnapshotSubmesh snapshot;
    snapshot.vertex_count = vertex_count;
    snapshot.vertex_indices = vertex_indices;
    snapshot.positions = positions;
    g_sparse_vertex_snapshots[snapshot_id][submesh_index] = std::move(snapshot);
}

std::map<int, Vec3> sparse_vertex_snapshot_positions_from_item(const JsonValue& item, int vertex_count) {
    std::string snapshot_id = string_or(item.get("native_sparse_snapshot_id"), "");
    if (snapshot_id.empty()) {
        snapshot_id = string_or(item.get("sparse_snapshot_id"), "");
    }
    if (snapshot_id.empty() || vertex_count <= 0) {
        return {};
    }
    const int submesh_index = int_or(item.get("index"), -1);
    if (submesh_index < 0) {
        return {};
    }
    const auto snapshot_found = g_sparse_vertex_snapshots.find(snapshot_id);
    if (snapshot_found == g_sparse_vertex_snapshots.end()) {
        return {};
    }
    const auto submesh_found = snapshot_found->second.find(submesh_index);
    if (submesh_found == snapshot_found->second.end()) {
        return {};
    }
    const SparseVertexSnapshotSubmesh& snapshot = submesh_found->second;
    if (snapshot.vertex_count != vertex_count || snapshot.vertex_indices.size() != snapshot.positions.size()) {
        return {};
    }
    const std::vector<int> requested = int_vector_from_binary_or_json(
        item,
        "vertex_indices_binary",
        "vertex_indices",
        "vertex_index_start",
        "vertex_index_count"
    );
    std::set<int> requested_set;
    for (const int index : requested) {
        if (index >= 0 && index < vertex_count) {
            requested_set.insert(index);
        }
    }
    std::map<int, Vec3> result;
    for (std::size_t offset = 0; offset < snapshot.vertex_indices.size(); ++offset) {
        const int index = snapshot.vertex_indices[offset];
        if (index < 0 || index >= vertex_count) {
            continue;
        }
        if (!requested_set.empty() && requested_set.find(index) == requested_set.end()) {
            continue;
        }
        result[index] = snapshot.positions[offset];
    }
    return result;
}

std::vector<Vec2> uvs_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key = "uvs_binary",
    const std::string& json_key = "uvs"
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return uvs_from_binary(binary);
    }
    return uvs_from_json(item.get(json_key));
}

std::vector<std::array<int, 3>> faces_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    return faces_from_binary_or_json_keys(item, "faces_binary", "faces", vertex_count);
}

std::vector<std::array<int, 3>> faces_from_binary_or_json_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t vertex_count
) {
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        return faces_from_binary(binary, vertex_count);
    }
    return faces_from_json(item.get(json_key), vertex_count);
}

std::set<int> selected_vertices_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::set<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number) {
            continue;
        }
        int index = -1;
        if (!strict_int_or(&item, index)) {
            continue;
        }
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::string normalized_selection_operation(std::string operation) {
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (operation == "extend") {
        operation = "add";
    } else if (operation == "remove") {
        operation = "subtract";
    }
    if (operation != "add" && operation != "subtract" && operation != "toggle") {
        operation = "replace";
    }
    return operation;
}

template <typename Value>
std::set<Value> combine_selection_sets(std::set<Value> current, const std::set<Value>& incoming, const std::string& operation) {
    if (operation == "add") {
        current.insert(incoming.begin(), incoming.end());
        return current;
    }
    if (operation == "subtract") {
        for (const Value& value : incoming) {
            current.erase(value);
        }
        return current;
    }
    if (operation == "toggle") {
        for (const Value& value : incoming) {
            const auto found = current.find(value);
            if (found == current.end()) {
                current.insert(value);
            } else {
                current.erase(found);
            }
        }
        return current;
    }
    return incoming;
}

const MeshEditorSession* mesh_editor_session_for_item(const JsonValue& item) {
    std::string session_id = string_or(item.get("editor_session_id"), "");
    if (session_id.empty()) {
        session_id = string_or(item.get("mesh_editor_session_id"), "");
    }
    if (session_id.empty() || int_or(item.get("index"), -1) < 0) {
        return nullptr;
    }
    const auto found = g_mesh_editor_sessions.find(session_id);
    return found == g_mesh_editor_sessions.end() ? nullptr : &found->second;
}

const MeshEditorSelection* mesh_editor_selection_for_item(const JsonValue& item) {
    const MeshEditorSession* session = mesh_editor_session_for_item(item);
    return session == nullptr ? nullptr : &session->selection;
}

std::set<int> mesh_editor_selected_indices_for_item(
    const JsonValue& item,
    const std::map<int, std::set<int>>& values_by_submesh,
    std::size_t item_count
) {
    std::set<int> result;
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = values_by_submesh.find(submesh_index);
    if (found == values_by_submesh.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < item_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_selected_edges_for_item(const JsonValue& item, std::size_t vertex_count) {
    std::set<std::array<int, 2>> result;
    const MeshEditorSelection* selection = mesh_editor_selection_for_item(item);
    if (selection == nullptr) {
        return result;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = selection->edges.find(submesh_index);
    if (found == selection->edges.end()) {
        return result;
    }
    for (const std::array<int, 2>& edge : found->second) {
        if (edge[0] >= 0 && edge[1] >= 0
            && static_cast<std::size_t>(edge[0]) < vertex_count
            && static_cast<std::size_t>(edge[1]) < vertex_count) {
            result.insert(edge);
        }
    }
    return result;
}

std::set<int> selected_vertices_from_binary_or_json_keys(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::string& binary_key,
    const std::string& json_key,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string()
) {
    std::set<int> result;
    const std::vector<int> values = int_vector_from_binary_or_json(
        item,
        binary_key,
        json_key,
        range_start_key,
        range_count_key
    );
    for (const int index : values) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> selected_vertices_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    std::set<int> result;
    if (bool_or(item.get("selected_all_vertices"), false)) {
        for (std::size_t index = 0; index < vertex_count; ++index) {
            result.insert(static_cast<int>(index));
        }
        return result;
    }
    result = selected_vertices_from_binary_or_json_keys(
        item,
        vertex_count,
        "selected_vertices_binary",
        "selected_vertices",
        "selected_vertex_start",
        "selected_vertex_count"
    );
    if (!result.empty()) {
        return result;
    }
    if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
        return mesh_editor_selected_indices_for_item(item, selection->vertices, vertex_count);
    }
    return result;
}

std::map<int, double> selected_vertex_weights_from_editor_session(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::set<int>* allowed,
    bool& has_weights
) {
    has_weights = false;
    std::map<int, double> weights;
    const MeshEditorSelection* selection = mesh_editor_selection_for_item(item);
    if (selection == nullptr) {
        return weights;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    const auto found = selection->vertex_weights.find(submesh_index);
    if (found == selection->vertex_weights.end()) {
        const std::set<int> selected = mesh_editor_selected_indices_for_item(item, selection->vertices, vertex_count);
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                continue;
            }
            if (allowed != nullptr && allowed->find(index) == allowed->end()) {
                continue;
            }
            weights[index] = 1.0;
        }
        has_weights = !weights.empty();
        return weights;
    }
    has_weights = true;
    for (const auto& entry : found->second) {
        const int index = entry.first;
        if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
            continue;
        }
        if (allowed != nullptr && allowed->find(index) == allowed->end()) {
            continue;
        }
        const double weight = std::max(0.0, std::min(1.0, entry.second));
        if (weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    }
    return weights;
}

std::set<int> selected_indices_from_binary_or_json(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t item_count,
    const std::string& range_start_key = std::string(),
    const std::string& range_count_key = std::string()
) {
    std::set<int> result;
    const std::vector<int> values = int_vector_from_binary_or_json(
        item,
        binary_key,
        json_key,
        range_start_key,
        range_count_key
    );
    for (const int index : values) {
        if (index >= 0 && static_cast<std::size_t>(index) < item_count) {
            result.insert(index);
        }
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<std::array<int, 3>> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            continue;
        }
        int a = -1;
        int b = -1;
        int c = -1;
        if (!strict_int_or(&item.array_value[0], a)
            || !strict_int_or(&item.array_value[1], b)
            || !strict_int_or(&item.array_value[2], c)) {
            continue;
        }
        if (a >= 0 && b >= 0 && c >= 0
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count
            && static_cast<std::size_t>(c) < vertex_count) {
            result.push_back({a, b, c});
        }
    }
    return result;
}

std::vector<int> source_face_indices_from_faces_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& item = value->array_value[face_index];
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            continue;
        }
        int a = -1;
        int b = -1;
        int c = -1;
        if (!strict_int_or(&item.array_value[0], a)
            || !strict_int_or(&item.array_value[1], b)
            || !strict_int_or(&item.array_value[2], c)) {
            continue;
        }
        if (a >= 0 && b >= 0 && c >= 0
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count
            && static_cast<std::size_t>(c) < vertex_count) {
            result.push_back(static_cast<int>(face_index));
        }
    }
    return result;
}

struct DisplayFace {
    std::vector<int> indices;
    int source_index = -1;
    bool valid = false;
};

std::vector<DisplayFace> display_faces_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<DisplayFace> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& item = value->array_value[face_index];
        DisplayFace face;
        face.source_index = static_cast<int>(face_index);
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 3) {
            result.push_back(std::move(face));
            continue;
        }
        bool valid = true;
        face.indices.reserve(item.array_value.size());
        for (const JsonValue& raw_index : item.array_value) {
            int vertex_index = -1;
            if (!strict_int_or(&raw_index, vertex_index)
                || vertex_index < 0
                || static_cast<std::size_t>(vertex_index) >= vertex_count) {
                valid = false;
                break;
            }
            face.indices.push_back(vertex_index);
        }
        face.valid = valid && face.indices.size() >= 3;
        if (!face.valid) {
            face.indices.clear();
        }
        result.push_back(std::move(face));
    }
    return result;
}

std::array<int, 2> edge_key(int a, int b) {
    return {std::min(a, b), std::max(a, b)};
}

std::vector<int> closed_edge_loop_order(const std::set<std::array<int, 2>>& edges) {
    std::vector<int> order;
    if (edges.size() != 3 && edges.size() != 4) {
        return order;
    }
    std::map<int, std::set<int>> adjacency;
    for (const auto& edge : edges) {
        if (edge[0] == edge[1]) {
            return {};
        }
        adjacency[edge[0]].insert(edge[1]);
        adjacency[edge[1]].insert(edge[0]);
    }
    if (adjacency.size() != edges.size()) {
        return {};
    }
    for (const auto& item_adjacency : adjacency) {
        if (item_adjacency.second.size() != 2) {
            return {};
        }
    }
    const int start = adjacency.begin()->first;
    int previous = start;
    int current = *adjacency[start].begin();
    order.push_back(start);
    while (current != start) {
        if (std::find(order.begin(), order.end(), current) != order.end()) {
            return {};
        }
        order.push_back(current);
        const std::set<int>& neighbors = adjacency[current];
        int next = -1;
        for (const int candidate : neighbors) {
            if (candidate != previous) {
                next = candidate;
                break;
            }
        }
        if (next < 0) {
            return {};
        }
        previous = current;
        current = next;
    }
    if (order.size() != adjacency.size()) {
        return {};
    }
    return order;
}

std::set<std::array<int, 2>> selected_edges_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::set<std::array<int, 2>> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        int a = -1;
        int b = -1;
        if (!strict_int_or(&item.array_value[0], a) || !strict_int_or(&item.array_value[1], b)) {
            continue;
        }
        if (a >= 0 && b >= 0 && a != b
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count) {
            result.insert(edge_key(a, b));
        }
    }
    return result;
}

std::set<std::array<int, 2>> selected_edges_from_binary_or_json_keys(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::string& binary_key,
    const std::string& json_key
) {
    std::set<std::array<int, 2>> result;
    const JsonValue* binary = item.get(binary_key);
    if (binary != nullptr) {
        const std::vector<int> raw = int_vector_from_binary(binary);
        for (std::size_t offset = 0; offset + 1 < raw.size(); offset += 2) {
            const int a = raw[offset];
            const int b = raw[offset + 1];
            if (a >= 0 && b >= 0 && a != b
                && static_cast<std::size_t>(a) < vertex_count
                && static_cast<std::size_t>(b) < vertex_count) {
                result.insert(edge_key(a, b));
            }
        }
        return result;
    }
    result = selected_edges_from_json(item.get(json_key), vertex_count);
    if (!result.empty()) {
        return result;
    }
    return mesh_editor_selected_edges_for_item(item, vertex_count);
}

std::set<std::array<int, 2>> selected_edges_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    return selected_edges_from_binary_or_json_keys(item, vertex_count, "selected_edges_binary", "selected_edges");
}

bool source_face_indices_are_identity(const std::vector<int>& source_faces) {
    for (std::size_t index = 0; index < source_faces.size(); ++index) {
        if (source_faces[index] != static_cast<int>(index)) {
            return false;
        }
    }
    return true;
}

std::set<int> compact_face_offsets_from_selection_values(
    const std::set<int>& selected_values,
    const std::vector<int>& source_faces,
    std::size_t face_count
) {
    std::set<int> result;
    if (selected_values.empty()) {
        return result;
    }
    if (source_faces.size() == face_count && !source_face_indices_are_identity(source_faces)) {
        for (std::size_t face_offset = 0; face_offset < source_faces.size(); ++face_offset) {
            if (selected_values.find(source_faces[face_offset]) != selected_values.end()) {
                result.insert(static_cast<int>(face_offset));
            }
        }
        return result;
    }
    for (const int index : selected_values) {
        if (index >= 0 && static_cast<std::size_t>(index) < face_count) {
            result.insert(index);
        }
    }
    return result;
}

std::vector<int> source_face_indices_for_selection(
    const JsonValue& item,
    const std::vector<std::array<int, 3>>& faces,
    std::size_t vertex_count
) {
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() == faces.size() && !source_face_indices_are_identity(source_faces)) {
        return source_faces;
    }
    if (item.get("source_face_indices_binary") == nullptr
        && item.get("source_face_indices") == nullptr
        && item.get("source_face_start") == nullptr
        && item.get("faces") != nullptr) {
        const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
        if (raw_source_faces.size() == faces.size()) {
            return raw_source_faces;
        }
    }
    return source_faces;
}

std::set<int> selected_faces_from_topology_json(
    const JsonValue& item,
    const std::vector<std::array<int, 3>>& faces,
    std::size_t vertex_count
) {
    std::set<int> selected_faces;
    const std::vector<int> source_faces = source_face_indices_for_selection(item, faces, vertex_count);
    const std::vector<int> explicit_selected_faces = int_vector_from_binary_or_json(
        item,
        "selected_faces_binary",
        "selected_faces",
        "selected_face_start",
        "selected_face_count"
    );
    for (const int index : explicit_selected_faces) {
        if (index >= 0) {
            selected_faces.insert(index);
        }
    }
    if (bool_or(item.get("selected_all_faces"), false)) {
        selected_faces.clear();
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            selected_faces.insert(static_cast<int>(face_index));
        }
        return selected_faces;
    }
    if (!selected_faces.empty()) {
        return compact_face_offsets_from_selection_values(selected_faces, source_faces, faces.size());
    }
    if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
        const int submesh_index = int_or(item.get("index"), -1);
        const auto found = selection->faces.find(submesh_index);
        if (found != selection->faces.end()) {
            selected_faces = compact_face_offsets_from_selection_values(found->second, source_faces, faces.size());
        }
        if (!selected_faces.empty()) {
            return selected_faces;
        }
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertex_count);
    if (!selected_edges.empty()) {
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            if (selected_edges.find(edge_key(face[0], face[1])) != selected_edges.end()
                || selected_edges.find(edge_key(face[1], face[2])) != selected_edges.end()
                || selected_edges.find(edge_key(face[2], face[0])) != selected_edges.end()) {
                selected_faces.insert(static_cast<int>(face_index));
            }
        }
        return selected_faces;
    }

    const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
    if (!selected_vertices.empty()) {
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            if (selected_vertices.find(face[0]) != selected_vertices.end()
                || selected_vertices.find(face[1]) != selected_vertices.end()
                || selected_vertices.find(face[2]) != selected_vertices.end()) {
                selected_faces.insert(static_cast<int>(face_index));
            }
        }
    }
    return selected_faces;
}

std::set<std::array<int, 2>> face_edge_set(const std::vector<std::array<int, 3>>& faces);

std::set<int> selected_prune_faces_from_keys(
    const JsonValue& item,
    const std::string& binary_key,
    const std::string& json_key,
    std::size_t selection_face_count,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& source_faces
) {
    std::set<int> selected_faces = selected_indices_from_binary_or_json(
        item,
        binary_key,
        json_key,
        selection_face_count,
        json_key == "current_selected_faces" ? "current_selected_face_start" : "selected_face_start",
        json_key == "current_selected_faces" ? "current_selected_face_count" : "selected_face_count"
    );
    if (!selected_faces.empty()
        && source_faces.size() == faces.size()
        && selection_face_count > faces.size()) {
        std::set<int> kept_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const int source_face_index = source_faces[face_offset];
            if (selected_faces.find(source_face_index) != selected_faces.end()) {
                kept_faces.insert(source_face_index);
            }
        }
        selected_faces = std::move(kept_faces);
    }
    return selected_faces;
}

std::set<int> selected_vertices_from_edit_domains(
    const JsonValue& item,
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
    if (bool_or(item.get("selected_all_vertices"), false)) {
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            selected_vertices.insert(static_cast<int>(vertex_index));
        }
    }

    std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertex_count);
    if (!faces.empty() && !selected_edges.empty()) {
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
        std::set<std::array<int, 2>> kept_edges;
        for (const auto& edge : selected_edges) {
            if (existing_edges.find(edge) != existing_edges.end()) {
                kept_edges.insert(edge);
            }
        }
        selected_edges = std::move(kept_edges);
    }
    for (const auto& edge : selected_edges) {
        selected_vertices.insert(edge[0]);
        selected_vertices.insert(edge[1]);
    }

    if (bool_or(item.get("selected_all_faces"), false)) {
        for (const auto& face : faces) {
            selected_vertices.insert(face[0]);
            selected_vertices.insert(face[1]);
            selected_vertices.insert(face[2]);
        }
    }
    const std::set<int> selected_faces = selected_indices_from_binary_or_json(
        item,
        "selected_faces_binary",
        "selected_faces",
        faces.size(),
        "selected_face_start",
        "selected_face_count"
    );
    if (selected_faces.empty()) {
        const std::vector<int> source_faces = source_face_indices_for_selection(item, faces, vertex_count);
        if (const MeshEditorSelection* selection = mesh_editor_selection_for_item(item)) {
            const int submesh_index = int_or(item.get("index"), -1);
            const auto found = selection->faces.find(submesh_index);
            if (found != selection->faces.end()) {
                for (const int face_index : compact_face_offsets_from_selection_values(found->second, source_faces, faces.size())) {
                    if (face_index >= 0 && static_cast<std::size_t>(face_index) < faces.size()) {
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][0]);
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][1]);
                        selected_vertices.insert(faces[static_cast<std::size_t>(face_index)][2]);
                    }
                }
            }
        }
    }
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
            continue;
        }
        const auto& face = faces[static_cast<std::size_t>(face_index)];
        selected_vertices.insert(face[0]);
        selected_vertices.insert(face[1]);
        selected_vertices.insert(face[2]);
    }
    return selected_vertices;
}

std::set<std::array<int, 2>> face_edge_set(const std::vector<std::array<int, 3>>& faces) {
    std::set<std::array<int, 2>> result;
    for (const auto& face : faces) {
        result.insert(edge_key(face[0], face[1]));
        result.insert(edge_key(face[1], face[2]));
        result.insert(edge_key(face[2], face[0]));
    }
    return result;
}

std::vector<std::set<int>> build_vertex_adjacency(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
);

std::set<int> mesh_editor_pruned_vertices_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t vertex_count
) {
    std::set<int> result;
    const auto found = selection.vertices.find(submesh_index);
    if (found == selection.vertices.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.insert(index);
        }
    }
    return result;
}

std::map<int, double> mesh_editor_pruned_vertex_weights_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    const std::set<int>& allowed_vertices
) {
    std::map<int, double> result;
    const auto found = selection.vertex_weights.find(submesh_index);
    if (found == selection.vertex_weights.end()) {
        return result;
    }
    for (const auto& entry : found->second) {
        if (allowed_vertices.find(entry.first) != allowed_vertices.end()) {
            result[entry.first] = std::max(0.0, std::min(1.0, entry.second));
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_pruned_edges_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::set<std::array<int, 2>> result;
    const auto found = selection.edges.find(submesh_index);
    if (found == selection.edges.end()) {
        return result;
    }
    for (const std::array<int, 2>& edge : found->second) {
        if (edge[0] >= 0 && edge[1] >= 0 && edge[0] != edge[1]
            && static_cast<std::size_t>(edge[0]) < vertex_count
            && static_cast<std::size_t>(edge[1]) < vertex_count) {
            result.insert(edge_key(edge[0], edge[1]));
        }
    }
    if (!faces.empty() && !result.empty()) {
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
        std::set<std::array<int, 2>> kept;
        for (const std::array<int, 2>& edge : result) {
            if (existing_edges.find(edge) != existing_edges.end()) {
                kept.insert(edge);
            }
        }
        result = std::move(kept);
    }
    return result;
}

std::set<int> mesh_editor_pruned_faces_for_submesh(
    const MeshEditorSelection& selection,
    int submesh_index,
    std::size_t face_count
) {
    std::set<int> result;
    const auto found = selection.faces.find(submesh_index);
    if (found == selection.faces.end()) {
        return result;
    }
    for (const int index : found->second) {
        if (index >= 0 && static_cast<std::size_t>(index) < face_count) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> mesh_editor_pruned_source_indices_for_session(
    const MeshEditorSession& session,
    const MeshEditorSelection& selection
) {
    std::set<int> result;
    for (const int index : selection.source_indices) {
        if (session.submeshes.find(index) != session.submeshes.end()) {
            result.insert(index);
        }
    }
    return result;
}

std::set<int> mesh_editor_selection_target_indices(const MeshEditorSelection& left, const MeshEditorSelection& right) {
    std::set<int> result;
    for (const auto& mapping : {left.vertices, right.vertices, left.faces, right.faces}) {
        for (const auto& entry : mapping) {
            if (entry.first >= 0) {
                result.insert(entry.first);
            }
        }
    }
    for (const auto& mapping : {left.edges, right.edges}) {
        for (const auto& entry : mapping) {
            if (entry.first >= 0) {
                result.insert(entry.first);
            }
        }
    }
    return result;
}

MeshEditorSelection mesh_editor_prune_and_combine_selection(
    const MeshEditorSession& session,
    const MeshEditorSelection& incoming,
    const std::string& operation
) {
    MeshEditorSelection result;
    result.source_indices = combine_selection_sets(
        mesh_editor_pruned_source_indices_for_session(session, session.selection),
        mesh_editor_pruned_source_indices_for_session(session, incoming),
        operation
    );
    const std::set<int> targets = mesh_editor_selection_target_indices(session.selection, incoming);
    for (const int submesh_index : targets) {
        const auto found = session.submeshes.find(submesh_index);
        if (found == session.submeshes.end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = found->second;
        const std::size_t vertex_count = submesh.vertices.size();
        const std::vector<std::array<int, 3>>& faces = submesh.faces;
        std::set<int> vertices = combine_selection_sets(
            mesh_editor_pruned_vertices_for_submesh(session.selection, submesh_index, vertex_count),
            mesh_editor_pruned_vertices_for_submesh(incoming, submesh_index, vertex_count),
            operation
        );
        if (!vertices.empty()) {
            std::map<int, double> weights;
            if (operation != "replace") {
                weights = mesh_editor_pruned_vertex_weights_for_submesh(session.selection, submesh_index, vertices);
            }
            if (operation != "subtract") {
                std::map<int, double> incoming_weights = mesh_editor_pruned_vertex_weights_for_submesh(incoming, submesh_index, vertices);
                for (const auto& entry : incoming_weights) {
                    weights[entry.first] = entry.second;
                }
            }
            if (!weights.empty()) {
                result.vertex_weights[submesh_index] = std::move(weights);
            }
            result.vertices[submesh_index] = std::move(vertices);
        }
        std::set<std::array<int, 2>> edges = combine_selection_sets(
            mesh_editor_pruned_edges_for_submesh(session.selection, submesh_index, vertex_count, faces),
            mesh_editor_pruned_edges_for_submesh(incoming, submesh_index, vertex_count, faces),
            operation
        );
        if (!edges.empty()) {
            result.edges[submesh_index] = std::move(edges);
        }
        std::set<int> selected_faces = combine_selection_sets(
            mesh_editor_pruned_faces_for_submesh(session.selection, submesh_index, faces.size()),
            mesh_editor_pruned_faces_for_submesh(incoming, submesh_index, faces.size()),
            operation
        );
        if (!selected_faces.empty()) {
            result.faces[submesh_index] = std::move(selected_faces);
        }
    }
    return result;
}

std::set<int> mesh_editor_vertices_from_selection_domains(
    const MeshEditorSelection& selection,
    int submesh_index,
    const MeshSessionSubmesh& submesh
) {
    std::set<int> selected = mesh_editor_pruned_vertices_for_submesh(selection, submesh_index, submesh.vertices.size());
    if (selection.source_indices.find(submesh_index) != selection.source_indices.end()) {
        for (std::size_t index = 0; index < submesh.vertices.size(); ++index) {
            selected.insert(static_cast<int>(index));
        }
    }
    std::set<std::array<int, 2>> selected_edges = mesh_editor_pruned_edges_for_submesh(selection, submesh_index, submesh.vertices.size(), submesh.faces);
    for (const std::array<int, 2>& edge : selected_edges) {
        selected.insert(edge[0]);
        selected.insert(edge[1]);
    }
    const std::set<int> selected_faces = mesh_editor_pruned_faces_for_submesh(selection, submesh_index, submesh.faces.size());
    for (const int face_index : selected_faces) {
        const std::array<int, 3>& face = submesh.faces[static_cast<std::size_t>(face_index)];
        selected.insert(face[0]);
        selected.insert(face[1]);
        selected.insert(face[2]);
    }
    return selected;
}

MeshEditorSelection mesh_editor_apply_selection_edit(
    const MeshEditorSession& session,
    const MeshEditorSelection& incoming,
    const std::string& operation,
    int iterations
) {
    MeshEditorSelection result;
    const bool all_operation = operation == "all";
    const bool invert_operation = operation == "invert";
    std::set<int> targets = mesh_editor_selection_target_indices(MeshEditorSelection{}, incoming);
    for (const int source_index : incoming.source_indices) {
        if (source_index >= 0) {
            targets.insert(source_index);
        }
    }
    for (const int submesh_index : targets) {
        const auto found = session.submeshes.find(submesh_index);
        if (found == session.submeshes.end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = found->second;
        if (submesh.vertices.empty()) {
            continue;
        }
        std::set<int> selected = mesh_editor_vertices_from_selection_domains(incoming, submesh_index, submesh);
        if (all_operation) {
            selected.clear();
            for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
                selected.insert(static_cast<int>(vertex_index));
            }
        } else if (invert_operation) {
            std::set<int> inverted;
            for (std::size_t vertex_index = 0; vertex_index < submesh.vertices.size(); ++vertex_index) {
                if (selected.find(static_cast<int>(vertex_index)) == selected.end()) {
                    inverted.insert(static_cast<int>(vertex_index));
                }
            }
            selected = std::move(inverted);
        } else if (!selected.empty()) {
            const std::vector<std::set<int>> adjacency = build_vertex_adjacency(submesh.vertices.size(), submesh.faces);
            for (int iteration = 0; iteration < std::max(0, iterations); ++iteration) {
                if (operation == "grow") {
                    std::set<int> next = selected;
                    for (const int vertex_index : selected) {
                        if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < adjacency.size()) {
                            next.insert(adjacency[static_cast<std::size_t>(vertex_index)].begin(), adjacency[static_cast<std::size_t>(vertex_index)].end());
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "shrink") {
                    std::set<int> next;
                    for (const int vertex_index : selected) {
                        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= adjacency.size()) {
                            continue;
                        }
                        const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(vertex_index)];
                        bool keep = neighbors.empty();
                        if (!keep) {
                            keep = true;
                            for (const int neighbor : neighbors) {
                                if (selected.find(neighbor) == selected.end()) {
                                    keep = false;
                                    break;
                                }
                            }
                        }
                        if (keep) {
                            next.insert(vertex_index);
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "smooth") {
                    std::set<int> next;
                    for (std::size_t vertex_index = 0; vertex_index < adjacency.size(); ++vertex_index) {
                        const std::set<int>& neighbors = adjacency[vertex_index];
                        const bool is_selected = selected.find(static_cast<int>(vertex_index)) != selected.end();
                        if (neighbors.empty()) {
                            if (is_selected) {
                                next.insert(static_cast<int>(vertex_index));
                            }
                            continue;
                        }
                        int selected_neighbors = 0;
                        for (const int neighbor : neighbors) {
                            if (selected.find(neighbor) != selected.end()) {
                                ++selected_neighbors;
                            }
                        }
                        const double ratio = static_cast<double>(selected_neighbors) / static_cast<double>(std::max<std::size_t>(1, neighbors.size()));
                        if ((is_selected && ratio >= 0.25) || (!is_selected && ratio >= 0.65)) {
                            next.insert(static_cast<int>(vertex_index));
                        }
                    }
                    selected = std::move(next);
                } else {
                    throw std::runtime_error("unsupported selection operation: " + operation);
                }
            }
        }
        if (!selected.empty()) {
            result.vertices[submesh_index] = std::move(selected);
        }
    }
    return result;
}

Transform transform_from_json(const JsonValue& root) {
    const JsonValue* transform = root.get("transform");
    if (transform == nullptr || transform->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing transform object");
    }
    Transform result;
    result.axis = transform_axis_constraint(*transform);
    result.translate = vec3_or(transform->get("translate"), result.translate);
    result.scale = vec3_or(transform->get("scale"), result.scale);
    result.rotate = vec3_or(transform->get("rotate"), result.rotate);
    result.translate = constrain_vec3_axis(result.translate, result.axis, {0.0, 0.0, 0.0});
    result.scale = constrain_vec3_axis(result.scale, result.axis, {1.0, 1.0, 1.0});
    result.rotate = constrain_vec3_axis(result.rotate, result.axis, {0.0, 0.0, 0.0});
    result.pivot = vec3_or(transform->get("pivot"), result.pivot);
    result.snap = std::max(0.0, number_or(transform->get("snap"), 0.0));
    result.mirror_x = bool_or(transform->get("mirror_x"), false);
    result.pivot_from_selection = bool_or(transform->get("pivot_from_selection"), false);
    result.recompute_normals = bool_or(transform->get("recompute_normals"), true);
    return result;
}

UvTransform uv_transform_from_json(const JsonValue& root) {
    const JsonValue* transform = root.get("uv_transform");
    if (transform == nullptr || transform->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing uv_transform object");
    }
    UvTransform result;
    result.offset = vec2_or(transform->get("offset"), result.offset);
    result.scale = vec2_or(transform->get("scale"), result.scale);
    result.rotate = number_or(transform->get("rotate"), 0.0);
    result.flip_u = bool_or(transform->get("flip_u"), false);
    result.flip_v = bool_or(transform->get("flip_v"), false);
    result.pivot = vec2_or(transform->get("pivot"), result.pivot);
    if (transform->get("input_bounds_min") != nullptr || transform->get("input_bounds_max") != nullptr) {
        result.validate_input_bounds = true;
        result.input_bounds_min = vec2_or(transform->get("input_bounds_min"), result.input_bounds_min);
        result.input_bounds_max = vec2_or(transform->get("input_bounds_max"), result.input_bounds_max);
    }
    result.clamp_input_uv = bool_or(transform->get("clamp_input_uv"), false);
    result.input_clamp_min = vec2_or(transform->get("input_clamp_min"), result.input_clamp_min);
    result.input_clamp_max = vec2_or(transform->get("input_clamp_max"), result.input_clamp_max);
    result.projection = lower_ascii(string_or(transform->get("projection"), result.projection));
    result.plane = lower_ascii(string_or(transform->get("plane"), result.plane));
    result.axis = lower_ascii(string_or(transform->get("axis"), result.axis));
    result.initialize_missing_uvs = bool_or(transform->get("initialize_missing_uvs"), false);
    result.normalize = bool_or(transform->get("normalize"), false);
    result.target_min = vec2_or(transform->get("target_min"), result.target_min);
    result.target_max = vec2_or(transform->get("target_max"), result.target_max);
    result.pack = bool_or(transform->get("pack"), false);
    result.pack_columns = std::max(0, int_or(transform->get("pack_columns"), 0));
    result.pack_padding = std::max(0.0, number_or(transform->get("padding"), number_or(transform->get("pack_padding"), result.pack_padding)));
    result.uv_island = bool_or(transform->get("uv_island"), bool_or(transform->get("island"), false));
    const std::string mode = lower_ascii(string_or(transform->get("mode"), ""));
    if (mode == "island" || mode == "uv_island") {
        result.uv_island = true;
    }
    result.snap_step = vec2_or(transform->get("snap_step"), result.snap_step);
    if (result.snap_step[0] <= 0.0 || result.snap_step[1] <= 0.0) {
        const double snap_grid = number_or(
            transform->get("snap_grid"),
            number_or(transform->get("snap_increment"), number_or(transform->get("grid"), 0.0))
        );
        if (snap_grid > 0.0) {
            result.snap_step = {snap_grid, snap_grid};
        }
    }
    if (bool_or(transform->get("pixel_snap"), bool_or(transform->get("snap_pixels"), false))) {
        const Vec2 texture_size = vec2_or(transform->get("texture_size"), {0.0, 0.0});
        if (texture_size[0] > 0.0 && texture_size[1] > 0.0) {
            result.snap_step = {1.0 / texture_size[0], 1.0 / texture_size[1]};
        }
    }
    result.snap = bool_or(transform->get("snap"), result.snap_step[0] > 0.0 || result.snap_step[1] > 0.0);
    uv_align_from_json(
        transform->get("align_u"),
        result.has_align_u,
        result.align_u_is_number,
        result.align_u_number,
        result.align_u_mode
    );
    uv_align_from_json(
        transform->get("align_v"),
        result.has_align_v,
        result.align_v_is_number,
        result.align_v_number,
        result.align_v_mode
    );
    return result;
}

double snap_value(double value, double increment) {
    if (increment <= 0.0) {
        return value;
    }
    const double snapped = std::nearbyint(value / increment) * increment;
    return std::abs(snapped) < 1e-12 ? 0.0 : snapped;
}

Vec3 snap_vertex(const Vec3& vertex, double increment) {
    return {
        snap_value(vertex[0], increment),
        snap_value(vertex[1], increment),
        snap_value(vertex[2], increment),
    };
}

Vec3 transform_vertex(const Vec3& vertex, const Transform& transform) {
    double x = (vertex[0] - transform.pivot[0]) * transform.scale[0];
    double y = (vertex[1] - transform.pivot[1]) * transform.scale[1];
    double z = (vertex[2] - transform.pivot[2]) * transform.scale[2];
    const double rx = transform.rotate[0] * 3.14159265358979323846 / 180.0;
    const double ry = transform.rotate[1] * 3.14159265358979323846 / 180.0;
    const double rz = transform.rotate[2] * 3.14159265358979323846 / 180.0;
    if (std::abs(rx) > 1e-8) {
        const double c = std::cos(rx);
        const double s = std::sin(rx);
        const double next_y = y * c - z * s;
        const double next_z = y * s + z * c;
        y = next_y;
        z = next_z;
    }
    if (std::abs(ry) > 1e-8) {
        const double c = std::cos(ry);
        const double s = std::sin(ry);
        const double next_x = x * c + z * s;
        const double next_z = -x * s + z * c;
        x = next_x;
        z = next_z;
    }
    if (std::abs(rz) > 1e-8) {
        const double c = std::cos(rz);
        const double s = std::sin(rz);
        const double next_x = x * c - y * s;
        const double next_y = x * s + y * c;
        x = next_x;
        y = next_y;
    }
    return snap_vertex(
        {
            transform.pivot[0] + x + transform.translate[0],
            transform.pivot[1] + y + transform.translate[1],
            transform.pivot[2] + z + transform.translate[2],
        },
        transform.snap
    );
}

bool same_vec3(const Vec3& left, const Vec3& right) {
    return std::abs(left[0] - right[0]) <= 1e-8
        && std::abs(left[1] - right[1]) <= 1e-8
        && std::abs(left[2] - right[2]) <= 1e-8;
}

double distance_squared_vec3(const Vec3& left, const Vec3& right) {
    const double dx = left[0] - right[0];
    const double dy = left[1] - right[1];
    const double dz = left[2] - right[2];
    return dx * dx + dy * dy + dz * dz;
}

Vec3 average_vertices(const std::vector<Vec3>& vertices, const std::vector<int>& indices) {
    Vec3 sum{0.0, 0.0, 0.0};
    if (indices.empty()) {
        return sum;
    }
    for (const int index : indices) {
        const Vec3& vertex = vertices[static_cast<std::size_t>(index)];
        sum[0] += vertex[0];
        sum[1] += vertex[1];
        sum[2] += vertex[2];
    }
    const double scale = 1.0 / static_cast<double>(indices.size());
    return {sum[0] * scale, sum[1] * scale, sum[2] * scale};
}

void accumulate_transform_selection_pivot(const JsonValue& item, const Transform& transform, Vec3& sum, std::size_t& count) {
    if (item.type != JsonValue::Type::Object) {
        return;
    }
    const int sparse_vertex_count = int_or(item.get("vertex_count"), 0);
    const std::map<int, Vec3> sparse_vertices = indexed_vertices_from_binary_or_json(item, sparse_vertex_count);
    const bool sparse_input = !sparse_vertices.empty() && !transform.mirror_x;
    if (sparse_input) {
        std::set<int> selected = selected_vertices_from_binary_or_json(item, static_cast<std::size_t>(sparse_vertex_count));
        if (selected.empty()) {
            for (const auto& sparse_item : sparse_vertices) {
                selected.insert(sparse_item.first);
            }
        }
        for (const int vertex_index : selected) {
            const auto found = sparse_vertices.find(vertex_index);
            if (found == sparse_vertices.end()) {
                continue;
            }
            sum[0] += found->second[0];
            sum[1] += found->second[1];
            sum[2] += found->second[2];
            ++count;
        }
        return;
    }

    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    if (vertices.empty()) {
        return;
    }
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    for (const int vertex_index : selected) {
        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
            continue;
        }
        const Vec3& vertex = vertices[static_cast<std::size_t>(vertex_index)];
        sum[0] += vertex[0];
        sum[1] += vertex[1];
        sum[2] += vertex[2];
        ++count;
    }
}

Vec3 transform_selection_pivot(const JsonValue& submeshes, const Transform& transform) {
    Vec3 sum{0.0, 0.0, 0.0};
    std::size_t count = 0;
    for (const JsonValue& item : submeshes.array_value) {
        accumulate_transform_selection_pivot(item, transform, sum, count);
    }
    if (count == 0) {
        return transform.pivot;
    }
    const double scale = 1.0 / static_cast<double>(count);
    return {sum[0] * scale, sum[1] * scale, sum[2] * scale};
}

std::map<int, int> mirror_pairs_from_json(const JsonValue* value, std::size_t vertex_count);
std::map<int, int> build_x_mirror_pairs_native(const std::vector<Vec3>& vertices);

std::vector<SubmeshTransformResult> run_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    Transform transform = transform_from_json(root);
    if (transform.pivot_from_selection) {
        transform.pivot = transform_selection_pivot(*submeshes, transform);
    }
    const JsonValue* transform_json = root.get("transform");
    const JsonValue* screen_drag = transform_json != nullptr && transform_json->type == JsonValue::Type::Object
        ? transform_json->get("screen_drag")
        : nullptr;
    std::vector<SubmeshTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        Transform item_transform = transform;
        const bool screen_drag_projection_payload = mesh_editor_has_projection_payload(screen_drag, result.index);
        const Vec3 base_translate = screen_drag_projection_payload ? Vec3{0.0, 0.0, 0.0} : transform.translate;
        item_transform.translate = constrain_vec3_axis(
            add_screen_drag_delta(base_translate, screen_drag, &transform.pivot, result.index),
            transform.axis,
            {0.0, 0.0, 0.0}
        );
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
        result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
        const int sparse_vertex_count = int_or(item.get("vertex_count"), 0);
        const std::map<int, Vec3> sparse_vertices = indexed_vertices_from_binary_or_json(item, sparse_vertex_count);
        const bool sparse_input = !sparse_vertices.empty() && !item_transform.mirror_x;
        const bool sparse_output = bool_or(item.get("sparse_output"), false);
        result.sparse = sparse_input;
        if (!sparse_input) {
            result.vertices = mesh_vertices_from_item(item);
        }
        const std::size_t vertex_count = sparse_input ? static_cast<std::size_t>(sparse_vertex_count) : result.vertices.size();
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertex_count);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::set<int> selected = selected_vertices_from_edit_domains(item, vertex_count, faces);
        if (sparse_input && selected.empty()) {
            for (const auto& sparse_item : sparse_vertices) {
                selected.insert(sparse_item.first);
            }
        }
        if (result.index < 0 || vertex_count == 0 || selected.empty()) {
            continue;
        }
        if (sparse_input) {
            for (const int vertex_index : selected) {
                const auto found = sparse_vertices.find(vertex_index);
                if (found == sparse_vertices.end()) {
                    continue;
                }
                const Vec3 old_vertex = found->second;
                const Vec3 new_vertex = transform_vertex(old_vertex, item_transform);
                if (!same_vec3(old_vertex, new_vertex)) {
                    result.changed_vertices.push_back(vertex_index);
                    result.changed_positions.push_back(new_vertex);
                    result.before_positions.push_back(old_vertex);
                }
            }
            if (!result.changed_vertices.empty()) {
                result.sparse_snapshot_id = sparse_snapshot_id;
                store_sparse_vertex_snapshot_values(
                    sparse_snapshot_id,
                    result.index,
                    sparse_vertex_count,
                    result.changed_vertices,
                    result.before_positions
                );
                results.push_back(std::move(result));
            }
            continue;
        }
        if (result.vertices.empty()) {
            continue;
        }
        std::map<int, bool> target_vertices;
        for (const int vertex_index : selected) {
            target_vertices[vertex_index] = false;
        }
        if (item_transform.mirror_x) {
            std::map<int, int> mirror_pairs = mirror_pairs_from_json(item.get("mirror_pairs"), result.vertices.size());
            if (mirror_pairs.empty()) {
                mirror_pairs = build_x_mirror_pairs_native(result.vertices);
            }
            for (const int vertex_index : selected) {
                const auto found = mirror_pairs.find(vertex_index);
                if (found != mirror_pairs.end()) {
                    target_vertices.emplace(found->second, true);
                }
            }
        }
        for (const auto& target : target_vertices) {
            const int vertex_index = target.first;
            const Vec3 old_vertex = result.vertices[static_cast<std::size_t>(vertex_index)];
            Transform local_transform = item_transform;
            if (target.second) {
                local_transform.translate[0] = -local_transform.translate[0];
            }
            const Vec3 new_vertex = transform_vertex(old_vertex, local_transform);
            if (!same_vec3(old_vertex, new_vertex)) {
                result.vertices[static_cast<std::size_t>(vertex_index)] = new_vertex;
                result.changed_vertices.push_back(vertex_index);
                result.before_positions.push_back(old_vertex);
                result.changed_positions.push_back(new_vertex);
            }
        }
        if (sparse_output) {
            result.sparse = true;
            result.changed_positions.clear();
            result.changed_positions.reserve(result.changed_vertices.size());
            for (const int vertex_index : result.changed_vertices) {
                if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < result.vertices.size()) {
                    result.changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                }
            }
        }
        if (!result.changed_vertices.empty()) {
            result.sparse_snapshot_id = sparse_snapshot_id;
            store_sparse_vertex_snapshot_values(
                sparse_snapshot_id,
                result.index,
                static_cast<int>(result.vertices.size()),
                result.changed_vertices,
                result.before_positions
            );
            if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                if (session->vertices.size() == result.vertices.size()) {
                    session->vertices = result.vertices;
                    session->tangents.clear();
                    session->tangent_signs.clear();
                    if (item_transform.recompute_normals && !session->faces.empty()) {
                        session->normals = compute_smooth_normals(session->vertices, session->faces);
                    } else if (item_transform.recompute_normals) {
                        session->normals.clear();
                    }
                }
            }
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<SubmeshTransformResult> run_restore_vertices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    std::vector<SubmeshTransformResult> results;
    std::map<int, std::set<int>> restored_indices_by_submesh;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
        result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
        result.sparse = true;
        if (result.index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const int explicit_vertex_count = int_or(item.get("vertex_count"), -1);
        const std::size_t vertex_count = vertices.empty() && explicit_vertex_count > 0
            ? static_cast<std::size_t>(explicit_vertex_count)
            : vertices.size();
        if (vertex_count == 0 || vertices.size() != vertex_count) {
            continue;
        }
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertex_count);
        std::map<int, Vec3> restore_positions = sparse_vertex_snapshot_positions_from_item(
            item,
            static_cast<int>(vertex_count)
        );
        if (restore_positions.empty()) {
            restore_positions = indexed_vertices_from_binary_or_json(
                item,
                static_cast<int>(vertex_count)
            );
        }
        if (restore_positions.empty()) {
            continue;
        }
        for (const auto& restore_item : restore_positions) {
            const int vertex_index = restore_item.first;
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            std::set<int>& restored_indices = restored_indices_by_submesh[result.index];
            if (restored_indices.find(vertex_index) != restored_indices.end()) {
                continue;
            }
            restored_indices.insert(vertex_index);
            const Vec3 old_vertex = vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 restored_vertex = restore_item.second;
            if (!same_vec3(old_vertex, restored_vertex)) {
                vertices[static_cast<std::size_t>(vertex_index)] = restored_vertex;
                result.changed_vertices.push_back(vertex_index);
                result.changed_positions.push_back(restored_vertex);
                result.before_positions.push_back(old_vertex);
            }
        }
        if (result.changed_vertices.empty()) {
            continue;
        }
        result.sparse_snapshot_id = sparse_snapshot_id;
        store_sparse_vertex_snapshot_values(
            sparse_snapshot_id,
            result.index,
            static_cast<int>(vertices.size()),
            result.changed_vertices,
            result.before_positions
        );
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (session->vertices.size() == vertices.size()) {
                session->vertices = vertices;
                session->normals.clear();
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshTransformResult> run_snapshot_vertices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    std::vector<SubmeshTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
        result.sparse = true;
        if (result.index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const int explicit_vertex_count = int_or(item.get("vertex_count"), -1);
        const std::size_t vertex_count = vertices.empty() && explicit_vertex_count > 0
            ? static_cast<std::size_t>(explicit_vertex_count)
            : vertices.size();
        if (vertex_count == 0 || vertices.size() != vertex_count) {
            continue;
        }
        const std::vector<int> requested = int_vector_from_binary_or_json(
            item,
            "vertex_indices_binary",
            "vertex_indices",
            "vertex_index_start",
            "vertex_index_count"
        );
        std::set<int> seen;
        for (const int vertex_index : requested) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            if (seen.find(vertex_index) != seen.end()) {
                continue;
            }
            seen.insert(vertex_index);
            result.changed_vertices.push_back(vertex_index);
            result.before_positions.push_back(vertices[static_cast<std::size_t>(vertex_index)]);
        }
        if (!result.changed_vertices.empty()) {
            result.sparse_snapshot_id = sparse_snapshot_id;
            store_sparse_vertex_snapshot_values(
                sparse_snapshot_id,
                result.index,
                static_cast<int>(vertex_count),
                result.changed_vertices,
                result.before_positions
            );
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<Vec2> remap_vec2_by_index_map(const std::vector<Vec2>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<Vec2> output(output_count, {0.0, 0.0});
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<Vec3> remap_vec3_by_index_map(const std::vector<Vec3>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<Vec3> output(output_count, {0.0, 0.0, 0.0});
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<double> remap_double_by_index_map(const std::vector<double>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<double> output(output_count, 0.0);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

std::vector<int> remap_int_by_index_map(const std::vector<int>& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (input.size() != index_map.size()) {
        return {};
    }
    std::vector<int> output(output_count, -1);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output[static_cast<std::size_t>(new_index)] = input[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

BoneAssignments remap_bones_by_index_map(const BoneAssignments& input, const std::vector<int>& index_map, std::size_t output_count) {
    if (!valid_bone_assignments(input) || input.indices.size() != index_map.size()) {
        return {};
    }
    BoneAssignments output;
    output.indices.resize(output_count);
    output.weights.resize(output_count);
    std::vector<char> filled(output_count, 0);
    for (std::size_t old_index = 0; old_index < index_map.size(); ++old_index) {
        const int new_index = index_map[old_index];
        if (new_index < 0) {
            continue;
        }
        if (static_cast<std::size_t>(new_index) >= output_count) {
            return {};
        }
        output.indices[static_cast<std::size_t>(new_index)] = input.indices[old_index];
        output.weights[static_cast<std::size_t>(new_index)] = input.weights[old_index];
        filled[static_cast<std::size_t>(new_index)] = 1;
    }
    for (const char value : filled) {
        if (!value) {
            return {};
        }
    }
    return output;
}

template <typename T>
std::vector<T> copy_values_by_vertex_remap(const std::vector<T>& input, const std::vector<int>& remap) {
    if (input.empty() || remap.empty()) {
        return {};
    }
    std::vector<T> output;
    output.reserve(remap.size());
    for (const int old_index : remap) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= input.size()) {
            return {};
        }
        output.push_back(input[static_cast<std::size_t>(old_index)]);
    }
    return output;
}

BoneAssignments copy_bones_by_vertex_remap(const BoneAssignments& input, const std::vector<int>& remap) {
    if (!valid_bone_assignments(input) || input.indices.empty() || input.indices.size() != input.weights.size()) {
        return {};
    }
    BoneAssignments output;
    output.indices.reserve(remap.size());
    output.weights.reserve(remap.size());
    for (const int old_index : remap) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= input.indices.size()) {
            return {};
        }
        output.indices.push_back(input.indices[static_cast<std::size_t>(old_index)]);
        output.weights.push_back(input.weights[static_cast<std::size_t>(old_index)]);
    }
    return output;
}

std::vector<SubmeshCleanupResult> run_cleanup(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    double threshold = 1e-5;
    const JsonValue* cleanup = root.get("cleanup");
    if (cleanup != nullptr && cleanup->type == JsonValue::Type::Object) {
        threshold = number_or(cleanup->get("threshold"), threshold);
    }
    if (!std::isfinite(threshold) || threshold <= 0.0) {
        threshold = 1e-5;
    }
    const double threshold_squared = threshold * threshold;
    std::vector<SubmeshCleanupResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::set<int> selected = selected_vertices_from_binary_or_json(item, vertices.size());
        if (index < 0 || vertices.empty() || selected.size() < 2) {
            continue;
        }
        const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
        const std::string faces_path = string_or(item.get("faces_output_path"), "");
        const std::string index_map_path = string_or(item.get("index_map_output_path"), "");
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
        const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
        const std::string tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        const std::string bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        const std::string bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        const std::string bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        const std::string source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        const std::string source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        const bool suppress_index_map_report = bool_or(item.get("suppress_index_map_report"), false);

        std::vector<int> remap(vertices.size(), 0);
        for (std::size_t i = 0; i < remap.size(); ++i) {
            remap[i] = static_cast<int>(i);
        }
        int merged_vertices = 0;
        for (const int keeper : selected) {
            if (remap[static_cast<std::size_t>(keeper)] != keeper) {
                continue;
            }
            std::vector<int> cluster{keeper};
            for (const int candidate : selected) {
                if (candidate <= keeper || remap[static_cast<std::size_t>(candidate)] != candidate) {
                    continue;
                }
                if (distance_squared_vec3(vertices[static_cast<std::size_t>(keeper)], vertices[static_cast<std::size_t>(candidate)]) <= threshold_squared) {
                    cluster.push_back(candidate);
                }
            }
            if (cluster.size() < 2) {
                continue;
            }
            vertices[static_cast<std::size_t>(keeper)] = average_vertices(vertices, cluster);
            for (std::size_t cluster_index = 1; cluster_index < cluster.size(); ++cluster_index) {
                remap[static_cast<std::size_t>(cluster[cluster_index])] = keeper;
                ++merged_vertices;
            }
        }

        std::set<std::array<int, 3>> seen_faces;
        std::vector<std::array<int, 3>> kept_faces;
        int degenerate_faces = 0;
        int duplicate_faces = 0;
        for (const auto& face : faces) {
            std::array<int, 3> remapped{
                remap[static_cast<std::size_t>(face[0])],
                remap[static_cast<std::size_t>(face[1])],
                remap[static_cast<std::size_t>(face[2])],
            };
            if (remapped[0] == remapped[1] || remapped[1] == remapped[2] || remapped[0] == remapped[2]) {
                ++degenerate_faces;
                continue;
            }
            if (seen_faces.find(remapped) != seen_faces.end()) {
                ++duplicate_faces;
                continue;
            }
            seen_faces.insert(remapped);
            kept_faces.push_back(remapped);
        }

        std::set<int> used_vertices;
        for (const auto& face : kept_faces) {
            used_vertices.insert(face[0]);
            used_vertices.insert(face[1]);
            used_vertices.insert(face[2]);
        }
        std::map<int, int> compacted_by_old;
        std::vector<Vec3> compacted_vertices;
        for (const int old_index : used_vertices) {
            compacted_by_old[old_index] = static_cast<int>(compacted_vertices.size());
            compacted_vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
        }
        std::vector<std::array<int, 3>> compacted_faces;
        for (const auto& face : kept_faces) {
            compacted_faces.push_back({
                compacted_by_old[face[0]],
                compacted_by_old[face[1]],
                compacted_by_old[face[2]],
            });
        }
        std::vector<int> index_map(vertices.size(), -1);
        for (std::size_t old_index = 0; old_index < vertices.size(); ++old_index) {
            if (remap[old_index] != static_cast<int>(old_index)) {
                continue;
            }
            const auto found = compacted_by_old.find(static_cast<int>(old_index));
            if (found != compacted_by_old.end()) {
                index_map[old_index] = found->second;
            }
        }

        const int removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(compacted_vertices.size());
        const int removed_faces = static_cast<int>(faces.size()) - static_cast<int>(compacted_faces.size());
        if (merged_vertices <= 0 && removed_vertices <= 0 && removed_faces <= 0) {
            continue;
        }
        SubmeshCleanupResult result;
        result.index = index;
        result.vertices_path = vertices_path;
        result.faces_path = faces_path;
        result.index_map_path = index_map_path;
        result.normals_path = normals_path;
        result.uvs_path = uvs_path;
        result.tangents_path = tangents_path;
        result.tangent_signs_path = tangent_signs_path;
        result.bone_counts_path = bone_counts_path;
        result.bone_indices_path = bone_indices_path;
        result.bone_weights_path = bone_weights_path;
        result.source_vertex_map_path = source_vertex_map_path;
        result.source_vertex_offsets_path = source_vertex_offsets_path;
        result.vertices = std::move(compacted_vertices);
        result.faces = std::move(compacted_faces);
        result.index_map = std::move(index_map);
        if (!result.normals_path.empty()) {
            result.normals = compute_smooth_normals(result.vertices, result.faces);
        }
        if (!result.uvs_path.empty()) {
            result.uvs = remap_vec2_by_index_map(mesh_uvs_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.tangents_path.empty()) {
            result.tangents = remap_vec3_by_index_map(mesh_tangents_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.tangent_signs_path.empty()) {
            result.tangent_signs = remap_double_by_index_map(mesh_tangent_signs_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.bone_counts_path.empty() && !result.bone_indices_path.empty() && !result.bone_weights_path.empty()) {
            result.bones = remap_bones_by_index_map(mesh_bones_from_item(item), result.index_map, result.vertices.size());
        }
        if (!result.source_vertex_map_path.empty()) {
            std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
                item,
                "source_vertex_map_binary",
                "source_vertex_map",
                "source_vertex_map_start",
                "source_vertex_map_count"
            );
            if (source_vertex_map.empty()) {
                if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                    source_vertex_map = session->source_vertex_map;
                }
            }
            result.source_vertex_map = remap_int_by_index_map(
                source_vertex_map,
                result.index_map,
                result.vertices.size());
        }
        if (!result.source_vertex_offsets_path.empty()) {
            std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
            if (source_vertex_offsets.empty()) {
                if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                    source_vertex_offsets = session->source_vertex_offsets;
                }
            }
            result.source_vertex_offsets = remap_int_by_index_map(
                source_vertex_offsets,
                result.index_map,
                result.vertices.size());
        }
        result.removed_vertices = removed_vertices;
        result.removed_faces = removed_faces;
        result.merged_vertices = merged_vertices;
        result.degenerate_faces = degenerate_faces;
        result.duplicate_faces = duplicate_faces;
        result.suppress_index_map_report = suppress_index_map_report;
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            session->vertices = result.vertices;
            session->faces = result.faces;
            session->source_face_indices = identity_indices(session->faces.size());
            session->normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
            session->uvs = result.uvs.size() == result.vertices.size() ? result.uvs : std::vector<Vec2>();
            session->tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
            session->tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
            if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                session->bone_indices = result.bones.indices;
                session->bone_weights = result.bones.weights;
            } else {
                session->bone_indices.clear();
                session->bone_weights.clear();
            }
            session->source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
            session->source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<float> meshopt_positions_from_vertices(const std::vector<Vec3>& vertices) {
    std::vector<float> positions;
    positions.reserve(vertices.size() * 3);
    for (const Vec3& vertex : vertices) {
        positions.push_back(static_cast<float>(vertex[0]));
        positions.push_back(static_cast<float>(vertex[1]));
        positions.push_back(static_cast<float>(vertex[2]));
    }
    return positions;
}

std::vector<unsigned int> meshopt_indices_from_faces(const std::vector<std::array<int, 3>>& faces) {
    std::vector<unsigned int> indices;
    indices.reserve(faces.size() * 3);
    for (const auto& face : faces) {
        indices.push_back(static_cast<unsigned int>(face[0]));
        indices.push_back(static_cast<unsigned int>(face[1]));
        indices.push_back(static_cast<unsigned int>(face[2]));
    }
    return indices;
}

std::vector<std::array<int, 3>> faces_from_meshopt_indices(const std::vector<unsigned int>& indices) {
    std::vector<std::array<int, 3>> faces;
    faces.reserve(indices.size() / 3);
    for (std::size_t i = 0; i + 2 < indices.size(); i += 3) {
        faces.push_back({
            static_cast<int>(indices[i]),
            static_cast<int>(indices[i + 1]),
            static_cast<int>(indices[i + 2]),
        });
    }
    return faces;
}

OptimizationStats meshopt_stats(
    const std::vector<unsigned int>& indices,
    const std::vector<float>& positions,
    std::size_t vertex_count
) {
    OptimizationStats stats;
    if (indices.empty() || vertex_count == 0 || positions.empty()) {
        return stats;
    }
    const meshopt_VertexCacheStatistics cache = meshopt_analyzeVertexCache(indices.data(), indices.size(), vertex_count, 16, 32, 0);
    const meshopt_OverdrawStatistics overdraw = meshopt_analyzeOverdraw(indices.data(), indices.size(), positions.data(), vertex_count, sizeof(float) * 3);
    const meshopt_VertexFetchStatistics fetch = meshopt_analyzeVertexFetch(indices.data(), indices.size(), vertex_count, sizeof(float) * 3);
    stats.cache_acmr = cache.acmr;
    stats.cache_atvr = cache.atvr;
    stats.overdraw = overdraw.overdraw;
    stats.overfetch = fetch.overfetch;
    return stats;
}

std::size_t meshopt_target_index_count(std::size_t input_index_count, double ratio) {
    if (!std::isfinite(ratio) || ratio <= 0.0 || ratio >= 1.0 || input_index_count < 6) {
        return input_index_count;
    }
    const std::size_t input_triangles = input_index_count / 3;
    std::size_t target_triangles = static_cast<std::size_t>(std::floor(static_cast<double>(input_triangles) * ratio));
    target_triangles = std::max<std::size_t>(1, target_triangles);
    const std::size_t target_index_count = target_triangles * 3;
    return std::min(input_index_count, target_index_count);
}

std::vector<SubmeshOptimizeResult> run_optimize(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    double simplify_ratio = 1.0;
    double target_error = 0.01;
    const JsonValue* optimize = root.get("optimize");
    if (optimize != nullptr && optimize->type == JsonValue::Type::Object) {
        simplify_ratio = number_or(optimize->get("simplify_ratio"), simplify_ratio);
        target_error = number_or(optimize->get("target_error"), target_error);
    }
    if (!std::isfinite(simplify_ratio) || simplify_ratio <= 0.0) {
        simplify_ratio = 1.0;
    }
    simplify_ratio = std::min(1.0, simplify_ratio);
    if (!std::isfinite(target_error) || target_error < 0.0) {
        target_error = 0.01;
    }

    std::vector<SubmeshOptimizeResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || faces.empty()) {
            continue;
        }

        const std::vector<float> positions = meshopt_positions_from_vertices(vertices);
        std::vector<unsigned int> indices = meshopt_indices_from_faces(faces);
        SubmeshOptimizeResult result;
        result.index = index;
        result.input_vertex_count = static_cast<int>(vertices.size());
        result.input_index_count = static_cast<int>(indices.size());
        result.input_triangle_count = static_cast<int>(indices.size() / 3);
        result.target_ratio = simplify_ratio;
        result.target_error = target_error;
        result.before = meshopt_stats(indices, positions, vertices.size());

        std::vector<unsigned int> optimized(indices.size());
        meshopt_optimizeVertexCache(optimized.data(), indices.data(), indices.size(), vertices.size());
        if (!optimized.empty()) {
            std::vector<unsigned int> overdraw(optimized.size());
            meshopt_optimizeOverdraw(overdraw.data(), optimized.data(), optimized.size(), positions.data(), vertices.size(), sizeof(float) * 3, 1.05f);
            optimized = std::move(overdraw);
        }

        const std::size_t target_index_count = meshopt_target_index_count(indices.size(), simplify_ratio);
        if (target_index_count < optimized.size()) {
            std::vector<unsigned int> simplified(optimized.size());
            float result_error = 0.0f;
            const std::size_t simplified_count = meshopt_simplify(
                simplified.data(),
                optimized.data(),
                optimized.size(),
                positions.data(),
                vertices.size(),
                sizeof(float) * 3,
                target_index_count,
                static_cast<float>(target_error),
                0,
                &result_error
            );
            if (simplified_count >= 3 && simplified_count < optimized.size()) {
                simplified.resize(simplified_count - (simplified_count % 3));
                optimized = std::move(simplified);
                result.result_error = result_error;
                result.simplified = true;
                if (!optimized.empty()) {
                    std::vector<unsigned int> recached(optimized.size());
                    meshopt_optimizeVertexCache(recached.data(), optimized.data(), optimized.size(), vertices.size());
                    optimized = std::move(recached);
                }
            }
        }

        std::vector<unsigned int> fetch_remap(vertices.size());
        result.fetch_vertex_count = static_cast<int>(meshopt_optimizeVertexFetchRemap(fetch_remap.data(), optimized.data(), optimized.size(), vertices.size()));
        result.referenced_vertex_count = result.fetch_vertex_count;
        result.output_index_count = static_cast<int>(optimized.size());
        result.output_triangle_count = static_cast<int>(optimized.size() / 3);
        result.topology_changed = result.output_index_count != result.input_index_count;
        result.after = meshopt_stats(optimized, positions, vertices.size());
        result.faces = faces_from_meshopt_indices(optimized);
        results.push_back(std::move(result));
    }
    return results;
}

Vec2 rotate_uv(const Vec2& value, const Vec2& pivot, double degrees) {
    const double radians = degrees * 3.14159265358979323846 / 180.0;
    const double cos_v = std::cos(radians);
    const double sin_v = std::sin(radians);
    const double u = value[0] - pivot[0];
    const double v = value[1] - pivot[1];
    return {
        pivot[0] + (u * cos_v - v * sin_v),
        pivot[1] + (u * sin_v + v * cos_v),
    };
}

bool same_vec2(const Vec2& left, const Vec2& right) {
    return std::abs(left[0] - right[0]) <= 1e-8
        && std::abs(left[1] - right[1]) <= 1e-8;
}

Vec2 transform_uv(const Vec2& uv, const UvTransform& transform) {
    double u = uv[0];
    double v = uv[1];
    if (transform.flip_u) {
        u = (2.0 * transform.pivot[0]) - u;
    }
    if (transform.flip_v) {
        v = (2.0 * transform.pivot[1]) - v;
    }
    u = transform.pivot[0] + ((u - transform.pivot[0]) * transform.scale[0]);
    v = transform.pivot[1] + ((v - transform.pivot[1]) * transform.scale[1]);
    Vec2 result{u, v};
    if (std::abs(transform.rotate) > 1e-8) {
        result = rotate_uv(result, transform.pivot, transform.rotate);
    }
    return {result[0] + transform.offset[0], result[1] + transform.offset[1]};
}

bool uv_transform_projects(const UvTransform& transform) {
    return transform.projection == "planar"
        || transform.projection == "xy"
        || transform.projection == "xz"
        || transform.projection == "yz"
        || transform.projection == "box"
        || transform.projection == "cube"
        || transform.projection == "cylindrical"
        || transform.projection == "cylinder";
}

std::array<int, 2> uv_plane_axes(const std::string& plane) {
    const std::string normalized = lower_ascii(plane.empty() ? "xy" : plane);
    if (normalized == "xz") {
        return {0, 2};
    }
    if (normalized == "yz") {
        return {1, 2};
    }
    return {0, 1};
}

std::map<int, Vec2> project_points_to_uvs(const std::map<int, Vec3>& points, const std::array<int, 2>& axes) {
    std::map<int, Vec2> result;
    if (points.empty()) {
        return result;
    }
    double left_min = 1.0e300;
    double left_max = -1.0e300;
    double right_min = 1.0e300;
    double right_max = -1.0e300;
    for (const auto& item : points) {
        const Vec3& point = item.second;
        left_min = std::min(left_min, point[axes[0]]);
        left_max = std::max(left_max, point[axes[0]]);
        right_min = std::min(right_min, point[axes[1]]);
        right_max = std::max(right_max, point[axes[1]]);
    }
    const double left_span = left_max - left_min;
    const double right_span = right_max - right_min;
    for (const auto& item : points) {
        const Vec3& point = item.second;
        result[item.first] = {
            std::abs(left_span) <= 1e-12 ? 0.0 : (point[axes[0]] - left_min) / left_span,
            std::abs(right_span) <= 1e-12 ? 0.0 : (point[axes[1]] - right_min) / right_span,
        };
    }
    return result;
}

std::array<int, 2> box_projection_axes(const Vec3& normal) {
    const double x = std::abs(normal[0]);
    const double y = std::abs(normal[1]);
    const double z = std::abs(normal[2]);
    if (x >= y && x >= z) {
        return {1, 2};
    }
    if (y >= x && y >= z) {
        return {0, 2};
    }
    return {0, 1};
}

std::map<int, Vec2> projected_uvs(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<int>& selected,
    const UvTransform& transform
) {
    std::map<int, Vec2> result;
    if (!uv_transform_projects(transform) || vertices.empty() || selected.empty()) {
        return result;
    }
    if (transform.projection == "cylindrical" || transform.projection == "cylinder") {
        std::array<int, 2> angle_axes{0, 1};
        int height_axis = 2;
        if (transform.axis == "x") {
            angle_axes = {1, 2};
            height_axis = 0;
        } else if (transform.axis == "y") {
            angle_axes = {0, 2};
            height_axis = 1;
        }
        double height_min = 1.0e300;
        double height_max = -1.0e300;
        for (const int index : selected) {
            if (index >= 0 && static_cast<std::size_t>(index) < vertices.size()) {
                height_min = std::min(height_min, vertices[static_cast<std::size_t>(index)][height_axis]);
                height_max = std::max(height_max, vertices[static_cast<std::size_t>(index)][height_axis]);
            }
        }
        const double height_span = height_max - height_min;
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            const Vec3& point = vertices[static_cast<std::size_t>(index)];
            result[index] = {
                (std::atan2(point[angle_axes[1]], point[angle_axes[0]]) + 3.14159265358979323846)
                    / (2.0 * 3.14159265358979323846),
                std::abs(height_span) <= 1e-12 ? 0.0 : (point[height_axis] - height_min) / height_span,
            };
        }
        return result;
    }
    if (transform.projection == "box" || transform.projection == "cube") {
        std::map<std::array<int, 2>, std::map<int, Vec3>> points_by_axes;
        for (const int index : selected) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            const Vec3 normal = static_cast<std::size_t>(index) < normals.size()
                ? normals[static_cast<std::size_t>(index)]
                : Vec3{0.0, 0.0, 1.0};
            points_by_axes[box_projection_axes(normal)][index] = vertices[static_cast<std::size_t>(index)];
        }
        for (const auto& item : points_by_axes) {
            const std::map<int, Vec2> projected = project_points_to_uvs(item.second, item.first);
            result.insert(projected.begin(), projected.end());
        }
        return result;
    }
    std::string plane = transform.plane;
    if (plane.empty() && (transform.projection == "xy" || transform.projection == "xz" || transform.projection == "yz")) {
        plane = transform.projection;
    }
    if (plane.empty()) {
        plane = "xy";
    }
    std::map<int, Vec3> points;
    for (const int index : selected) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertices.size()) {
            points[index] = vertices[static_cast<std::size_t>(index)];
        }
    }
    return project_points_to_uvs(points, uv_plane_axes(plane));
}

void normalize_uv_indices(std::vector<Vec2>& uvs, const std::vector<int>& selected, const Vec2& target_min, const Vec2& target_max) {
    if (selected.empty()) {
        return;
    }
    double min_u = 1.0e300;
    double max_u = -1.0e300;
    double min_v = 1.0e300;
    double max_v = -1.0e300;
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        const Vec2& uv = uvs[static_cast<std::size_t>(index)];
        min_u = std::min(min_u, uv[0]);
        max_u = std::max(max_u, uv[0]);
        min_v = std::min(min_v, uv[1]);
        max_v = std::max(max_v, uv[1]);
    }
    const double span_u = max_u - min_u;
    const double span_v = max_v - min_v;
    const double target_span_u = target_max[0] - target_min[0];
    const double target_span_v = target_max[1] - target_min[1];
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        uv = {
            std::abs(span_u) <= 1e-12 ? target_min[0] : target_min[0] + ((uv[0] - min_u) / span_u) * target_span_u,
            std::abs(span_v) <= 1e-12 ? target_min[1] : target_min[1] + ((uv[1] - min_v) / span_v) * target_span_v,
        };
    }
}

long long rounded_uv_component(double value) {
    const long long rounded = static_cast<long long>(std::llround(value * 1000000.0));
    return rounded == 0 ? 0 : rounded;
}

using PackedUvEdgeKey = std::tuple<int, int, long long, long long, long long, long long>;

PackedUvEdgeKey packed_uv_edge_key(int left, int right, const std::vector<Vec2>& uvs) {
    const std::array<int, 2> vertex_edge = edge_key(left, right);
    std::pair<long long, long long> left_uv{
        rounded_uv_component(uvs[static_cast<std::size_t>(left)][0]),
        rounded_uv_component(uvs[static_cast<std::size_t>(left)][1]),
    };
    std::pair<long long, long long> right_uv{
        rounded_uv_component(uvs[static_cast<std::size_t>(right)][0]),
        rounded_uv_component(uvs[static_cast<std::size_t>(right)][1]),
    };
    if (right_uv < left_uv) {
        std::swap(left_uv, right_uv);
    }
    return {
        vertex_edge[0],
        vertex_edge[1],
        left_uv.first,
        left_uv.second,
        right_uv.first,
        right_uv.second,
    };
}

std::vector<std::set<int>> selected_uv_islands(
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec2>& uvs,
    const std::vector<int>& selected
) {
    std::set<int> selected_set(selected.begin(), selected.end());
    if (selected_set.empty()) {
        return {};
    }
    std::map<PackedUvEdgeKey, std::set<int>> edge_faces;
    std::vector<std::vector<PackedUvEdgeKey>> face_edges;
    std::vector<std::array<int, 3>> face_vertices;
    std::set<int> seed_faces;
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        face_vertices.push_back(face);
        if (selected_set.find(face[0]) != selected_set.end()
            || selected_set.find(face[1]) != selected_set.end()
            || selected_set.find(face[2]) != selected_set.end()) {
            seed_faces.insert(static_cast<int>(face_index));
        }
        std::vector<PackedUvEdgeKey> edges;
        for (int edge_index = 0; edge_index < 3; ++edge_index) {
            const int left = face[edge_index];
            const int right = face[(edge_index + 1) % 3];
            if (left < 0 || right < 0 || static_cast<std::size_t>(left) >= uvs.size() || static_cast<std::size_t>(right) >= uvs.size()) {
                continue;
            }
            edges.push_back(packed_uv_edge_key(left, right, uvs));
            edge_faces[edges.back()].insert(static_cast<int>(face_index));
        }
        face_edges.push_back(std::move(edges));
    }

    std::set<int> visited;
    std::vector<std::set<int>> islands;
    for (const int seed_face : seed_faces) {
        std::vector<int> pending{seed_face};
        std::set<int> island_faces;
        while (!pending.empty()) {
            const int face_index = pending.back();
            pending.pop_back();
            if (face_index < 0
                || static_cast<std::size_t>(face_index) >= face_edges.size()
                || visited.find(face_index) != visited.end()) {
                continue;
            }
            visited.insert(face_index);
            island_faces.insert(face_index);
            for (const PackedUvEdgeKey& edge : face_edges[static_cast<std::size_t>(face_index)]) {
                const auto found = edge_faces.find(edge);
                if (found == edge_faces.end()) {
                    continue;
                }
                for (const int connected_face : found->second) {
                    if (visited.find(connected_face) == visited.end()) {
                        pending.push_back(connected_face);
                    }
                }
            }
        }
        std::set<int> island_vertices;
        for (const int face_index : island_faces) {
            const std::array<int, 3>& face = face_vertices[static_cast<std::size_t>(face_index)];
            for (const int vertex_index : face) {
                island_vertices.insert(vertex_index);
            }
        }
        if (!island_vertices.empty()) {
            islands.push_back(std::move(island_vertices));
        }
    }
    std::set<int> packed_vertices;
    for (const std::set<int>& island : islands) {
        packed_vertices.insert(island.begin(), island.end());
    }
    for (const int index : selected_set) {
        if (packed_vertices.find(index) == packed_vertices.end()) {
            islands.push_back(std::set<int>{index});
        }
    }
    std::sort(islands.begin(), islands.end(), [](const std::set<int>& left, const std::set<int>& right) {
        return *left.begin() < *right.begin();
    });
    return islands;
}

void pack_uvs(
    std::vector<Vec2>& uvs,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& selected,
    const UvTransform& transform
) {
    const std::vector<std::set<int>> islands = selected_uv_islands(faces, uvs, selected);
    if (islands.empty()) {
        return;
    }
    const int columns = transform.pack_columns > 0
        ? transform.pack_columns
        : std::max(1, static_cast<int>(std::ceil(std::sqrt(static_cast<double>(islands.size())))));
    const int rows = std::max(1, static_cast<int>(std::ceil(static_cast<double>(islands.size()) / static_cast<double>(columns))));
    const double cell_width = 1.0 / static_cast<double>(columns);
    const double cell_height = 1.0 / static_cast<double>(rows);
    const double inset_u = std::min(std::max(0.0, transform.pack_padding), cell_width * 0.45);
    const double inset_v = std::min(std::max(0.0, transform.pack_padding), cell_height * 0.45);
    for (std::size_t island_index = 0; island_index < islands.size(); ++island_index) {
        const int column = static_cast<int>(island_index) % columns;
        const int row = static_cast<int>(island_index) / columns;
        const Vec2 target_min{
            column * cell_width + inset_u,
            row * cell_height + inset_v,
        };
        const Vec2 target_max{
            (column + 1) * cell_width - inset_u,
            (row + 1) * cell_height - inset_v,
        };
        std::vector<int> island_vertices(islands[island_index].begin(), islands[island_index].end());
        normalize_uv_indices(uvs, island_vertices, target_min, target_max);
    }
}

bool uv_align_value(
    bool has_value,
    bool is_number,
    double number,
    const std::string& mode,
    const std::vector<double>& values,
    double& out
) {
    if (!has_value || values.empty()) {
        return false;
    }
    if (is_number) {
        out = number;
        return std::isfinite(out);
    }
    const auto minmax = std::minmax_element(values.begin(), values.end());
    if (mode == "min" || mode == "left" || mode == "bottom") {
        out = *minmax.first;
        return true;
    }
    if (mode == "max" || mode == "right" || mode == "top") {
        out = *minmax.second;
        return true;
    }
    if (mode == "center" || mode == "middle") {
        out = (*minmax.first + *minmax.second) / 2.0;
        return true;
    }
    char* end = nullptr;
    errno = 0;
    const double parsed = std::strtod(mode.c_str(), &end);
    if (end != mode.c_str() && end != nullptr && *end == '\0' && errno != ERANGE && std::isfinite(parsed)) {
        out = parsed;
        return true;
    }
    return false;
}

void align_uvs(std::vector<Vec2>& uvs, const std::vector<int>& selected, const UvTransform& transform) {
    std::vector<double> u_values;
    std::vector<double> v_values;
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        const Vec2& uv = uvs[static_cast<std::size_t>(index)];
        u_values.push_back(uv[0]);
        v_values.push_back(uv[1]);
    }
    double align_u = 0.0;
    double align_v = 0.0;
    const bool has_u = uv_align_value(transform.has_align_u, transform.align_u_is_number, transform.align_u_number, transform.align_u_mode, u_values, align_u);
    const bool has_v = uv_align_value(transform.has_align_v, transform.align_v_is_number, transform.align_v_number, transform.align_v_mode, v_values, align_v);
    if (!has_u && !has_v) {
        return;
    }
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        if (has_u) {
            uv[0] = align_u;
        }
        if (has_v) {
            uv[1] = align_v;
        }
    }
}

void snap_uvs(std::vector<Vec2>& uvs, const std::vector<int>& selected, const UvTransform& transform) {
    if (!transform.snap || transform.snap_step[0] <= 0.0 || transform.snap_step[1] <= 0.0) {
        return;
    }
    for (const int index : selected) {
        if (index < 0 || static_cast<std::size_t>(index) >= uvs.size()) {
            continue;
        }
        Vec2& uv = uvs[static_cast<std::size_t>(index)];
        uv[0] = snap_value(uv[0], transform.snap_step[0]);
        uv[1] = snap_value(uv[1], transform.snap_step[1]);
    }
}

std::vector<SubmeshUvTransformResult> run_uv_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const UvTransform root_transform = uv_transform_from_json(root);
    std::vector<SubmeshUvTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const UvTransform transform = item.get("uv_transform") != nullptr ? uv_transform_from_json(item) : root_transform;
        SubmeshUvTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.uvs = mesh_uvs_from_item(item);
        result.vertices = mesh_vertices_from_item(item);
        result.normals = mesh_normals_from_item(item);
        const int vertex_count = static_cast<int>(mesh_vertex_count_from_item(item));
        const bool projects = uv_transform_projects(transform);
        const bool initialized_uvs = (transform.initialize_missing_uvs || projects)
            && vertex_count >= 0
            && static_cast<std::size_t>(vertex_count) != result.uvs.size();
        if (initialized_uvs) {
            result.uvs.assign(static_cast<std::size_t>(vertex_count), {0.0, 0.0});
        }
        if (result.index < 0 || result.uvs.empty() || vertex_count < 0 || static_cast<std::size_t>(vertex_count) != result.uvs.size()) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.uvs.size());
        const std::set<int> selected = selected_vertices_from_edit_domains(item, result.uvs.size(), faces);
        if (selected.empty()) {
            continue;
        }
        std::vector<int> selected_ordered;
        selected_ordered.reserve(selected.size());
        for (const int vertex_index : selected) {
            if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < result.uvs.size()) {
                selected_ordered.push_back(vertex_index);
            }
        }
        if (selected_ordered.empty()) {
            continue;
        }
        const std::vector<Vec2> original_uvs = result.uvs;
        if (transform.uv_island) {
            std::set<int> island_vertices;
            for (const std::set<int>& island : selected_uv_islands(faces, result.uvs, selected_ordered)) {
                island_vertices.insert(island.begin(), island.end());
            }
            selected_ordered.assign(island_vertices.begin(), island_vertices.end());
            if (selected_ordered.empty()) {
                continue;
            }
        }
        const std::vector<Vec3> vertices = (projects || transform.pack) ? mesh_vertices_from_item(item) : std::vector<Vec3>();
        const std::vector<Vec3> normals = projects ? mesh_normals_from_item(item) : std::vector<Vec3>();
        if ((projects || transform.pack) && !vertices.empty() && vertices.size() != result.uvs.size()) {
            continue;
        }
        if (projects && vertices.empty()) {
            continue;
        }
        const std::map<int, Vec2> projected = projected_uvs(vertices, normals, selected_ordered, transform);
        for (const int vertex_index : selected_ordered) {
            const Vec2 old_uv = result.uvs[static_cast<std::size_t>(vertex_index)];
            if (transform.validate_input_bounds
                && (old_uv[0] < transform.input_bounds_min[0]
                    || old_uv[0] > transform.input_bounds_max[0]
                    || old_uv[1] < transform.input_bounds_min[1]
                    || old_uv[1] > transform.input_bounds_max[1])) {
                result.status = "uv_out_of_bounds";
                result.error = "input UV outside allowed bounds";
                result.invalid_vertex_index = vertex_index;
                result.invalid_uv = old_uv;
                result.changed_vertices.clear();
                break;
            }
            Vec2 input_uv = old_uv;
            const auto projected_found = projected.find(vertex_index);
            if (projected_found != projected.end()) {
                input_uv = projected_found->second;
            }
            if (transform.clamp_input_uv) {
                input_uv[0] = std::max(transform.input_clamp_min[0], std::min(transform.input_clamp_max[0], input_uv[0]));
                input_uv[1] = std::max(transform.input_clamp_min[1], std::min(transform.input_clamp_max[1], input_uv[1]));
            }
            const Vec2 new_uv = transform_uv(input_uv, transform);
            result.uvs[static_cast<std::size_t>(vertex_index)] = new_uv;
        }
        if (result.status != "ok") {
            results.push_back(std::move(result));
            continue;
        }
        if (transform.normalize) {
            normalize_uv_indices(result.uvs, selected_ordered, transform.target_min, transform.target_max);
        }
        if (transform.pack) {
            pack_uvs(result.uvs, faces, selected_ordered, transform);
        }
        align_uvs(result.uvs, selected_ordered, transform);
        snap_uvs(result.uvs, selected_ordered, transform);
        for (const int vertex_index : selected_ordered) {
            if (initialized_uvs
                || !same_vec2(
                    original_uvs[static_cast<std::size_t>(vertex_index)],
                    result.uvs[static_cast<std::size_t>(vertex_index)]
                )) {
                result.changed_vertices.push_back(vertex_index);
            }
        }
        if (result.status == "ok" && !result.changed_vertices.empty()) {
            if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                if (session->vertices.size() == result.uvs.size()) {
                    session->uvs = result.uvs;
                }
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

Vec3 face_normal(const Vec3& v0, const Vec3& v1, const Vec3& v2) {
    const double ax = v1[0] - v0[0];
    const double ay = v1[1] - v0[1];
    const double az = v1[2] - v0[2];
    const double bx = v2[0] - v0[0];
    const double by = v2[1] - v0[1];
    const double bz = v2[2] - v0[2];
    const double nx = ay * bz - az * by;
    const double ny = az * bx - ax * bz;
    const double nz = ax * by - ay * bx;
    const double length = std::sqrt(nx * nx + ny * ny + nz * nz);
    if (length > 1e-8) {
        return {nx / length, ny / length, nz / length};
    }
    return {0.0, 1.0, 0.0};
}

Vec3 normalized_vec3_or_zero(const Vec3& value) {
    const double length = std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
    if (length > 1e-12 && std::isfinite(length)) {
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    return {0.0, 0.0, 0.0};
}

Vec3 face_cross(const Vec3& v0, const Vec3& v1, const Vec3& v2) {
    const double ax = v1[0] - v0[0];
    const double ay = v1[1] - v0[1];
    const double az = v1[2] - v0[2];
    const double bx = v2[0] - v0[0];
    const double by = v2[1] - v0[1];
    const double bz = v2[2] - v0[2];
    return {ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx};
}

std::vector<Vec3> compute_smooth_normals(const std::vector<Vec3>& vertices, const std::vector<std::array<int, 3>>& faces) {
    std::vector<Vec3> normals(vertices.size(), {0.0, 0.0, 0.0});
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 normal = face_normal(vertices[static_cast<std::size_t>(a)], vertices[static_cast<std::size_t>(b)], vertices[static_cast<std::size_t>(c)]);
        for (const int index : face) {
            Vec3& target = normals[static_cast<std::size_t>(index)];
            target[0] += normal[0];
            target[1] += normal[1];
            target[2] += normal[2];
        }
    }
    for (Vec3& normal : normals) {
        const double length = std::sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
        if (length > 1e-8) {
            normal = {normal[0] / length, normal[1] / length, normal[2] / length};
        } else {
            normal = {0.0, 1.0, 0.0};
        }
    }
    return normals;
}

std::vector<Vec3> compute_weighted_normals(
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec3>& fallback_normals
) {
    auto normalized_or = [](const Vec3& value, const Vec3& fallback) -> Vec3 {
        const double length = std::sqrt(value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
        if (length > 1e-12 && std::isfinite(length)) {
            return {value[0] / length, value[1] / length, value[2] / length};
        }
        return fallback;
    };
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 weighted = face_cross(
            vertices[static_cast<std::size_t>(a)],
            vertices[static_cast<std::size_t>(b)],
            vertices[static_cast<std::size_t>(c)]
        );
        const double length_squared = weighted[0] * weighted[0] + weighted[1] * weighted[1] + weighted[2] * weighted[2];
        if (length_squared <= 1e-24 || !std::isfinite(length_squared)) {
            continue;
        }
        for (const int index : face) {
            Vec3& target = accum[static_cast<std::size_t>(index)];
            target[0] += weighted[0];
            target[1] += weighted[1];
            target[2] += weighted[2];
        }
    }
    std::vector<Vec3> result;
    result.reserve(vertices.size());
    for (std::size_t index = 0; index < accum.size(); ++index) {
        Vec3 normal = normalized_or(accum[index], {0.0, 0.0, 0.0});
        if (normal == Vec3{0.0, 0.0, 0.0} && index < fallback_normals.size()) {
            normal = normalized_or(fallback_normals[index], {0.0, 0.0, 0.0});
        }
        result.push_back(normal == Vec3{0.0, 0.0, 0.0} ? Vec3{0.0, 1.0, 0.0} : normal);
    }
    return result;
}

std::vector<SubmeshNormalsResult> run_recalculate_normals(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string operation = string_or(root.get("operation"), "recalculate_normals");
    std::vector<SubmeshNormalsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || (faces.empty() && operation != "copy_normals")) {
            continue;
        }
        SubmeshNormalsResult result;
        result.index = index;
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.preview_vertex_path = string_or(item.get("preview_vertex_output_path"), "");
        result.vertices = vertices;
        result.uvs = mesh_uvs_from_item(item);
        result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
        const std::vector<Vec3> existing_normals = mesh_normals_from_item(item);
        if (operation == "weighted_normals") {
            result.normals = compute_weighted_normals(vertices, faces, existing_normals);
        } else if (operation == "copy_normals") {
            const std::vector<Vec3> source_normals = vertices_from_binary_or_json(item, "source_normals_binary", "source_normals");
            const std::set<int> selected_vertices = selected_vertices_from_edit_domains(item, vertices.size(), faces);
            if (source_normals.empty() || selected_vertices.empty()) {
                continue;
            }
            result.normals = existing_normals.size() == vertices.size()
                ? existing_normals
                : std::vector<Vec3>(vertices.size(), {0.0, 0.0, 1.0});
            for (const int vertex_index : selected_vertices) {
                if (vertex_index < 0
                    || static_cast<std::size_t>(vertex_index) >= result.normals.size()
                    || static_cast<std::size_t>(vertex_index) >= source_normals.size()) {
                    continue;
                }
                const Vec3 normal = normalized_vec3_or_zero(source_normals[static_cast<std::size_t>(vertex_index)]);
                if (normal != Vec3{0.0, 0.0, 0.0}) {
                    result.normals[static_cast<std::size_t>(vertex_index)] = normal;
                }
            }
        } else if (operation == "sharpen_normals") {
            std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
            if (selected_faces.empty()) {
                continue;
            }
            result.normals = existing_normals.size() == vertices.size()
                ? existing_normals
                : std::vector<Vec3>(vertices.size(), {0.0, 0.0, 1.0});
            for (const int face_index : selected_faces) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
                    continue;
                }
                const std::array<int, 3>& face = faces[static_cast<std::size_t>(face_index)];
                const Vec3 normal = face_normal(
                    vertices[static_cast<std::size_t>(face[0])],
                    vertices[static_cast<std::size_t>(face[1])],
                    vertices[static_cast<std::size_t>(face[2])]
                );
                for (const int vertex_index : face) {
                    result.normals[static_cast<std::size_t>(vertex_index)] = normal;
                }
            }
        } else if (operation == "flip_normals") {
            std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
            if (selected_faces.empty()) {
                continue;
            }
            result.faces = faces;
            for (const int face_index : selected_faces) {
                if (face_index >= 0 && static_cast<std::size_t>(face_index) < result.faces.size()) {
                    std::swap(result.faces[static_cast<std::size_t>(face_index)][1], result.faces[static_cast<std::size_t>(face_index)][2]);
                }
            }
            if (bool_or(item.get("selected_all_faces"), false) && existing_normals.size() == vertices.size()) {
                result.normals.reserve(existing_normals.size());
                for (const Vec3& normal : existing_normals) {
                    result.normals.push_back({-normal[0], -normal[1], -normal[2]});
                }
            } else {
                result.normals = compute_smooth_normals(vertices, result.faces);
            }
        } else {
            result.normals = compute_smooth_normals(vertices, faces);
        }
        if (existing_normals.size() == result.normals.size()) {
            for (std::size_t normal_index = 0; normal_index < result.normals.size(); ++normal_index) {
                if (!same_vec3(existing_normals[normal_index], result.normals[normal_index])) {
                    result.changed_vertices.push_back(static_cast<int>(normal_index));
                }
            }
        } else {
            result.changed_vertices.reserve(result.normals.size());
            for (std::size_t normal_index = 0; normal_index < result.normals.size(); ++normal_index) {
                result.changed_vertices.push_back(static_cast<int>(normal_index));
            }
        }
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (result.faces.empty()) {
                if (session->vertices.size() == vertices.size()) {
                    session->normals = result.normals;
                }
            } else if (session->vertices.size() == vertices.size()) {
                session->faces = result.faces;
                session->normals = result.normals;
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshAutoUvResult> run_auto_uv(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    int resolution = int_or(root.get("atlas_size"), 0);
    const JsonValue* auto_uv = root.get("auto_uv");
    if (auto_uv != nullptr && auto_uv->type == JsonValue::Type::Object) {
        resolution = int_or(auto_uv->get("resolution"), resolution);
    }
    if (resolution < 0) {
        resolution = 0;
    }

    std::vector<SubmeshAutoUvResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshAutoUvResult result;
        result.index = int_or(item.get("index"), -1);
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.vertex_remap_path = string_or(item.get("vertex_remap_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.tangents_path = string_or(item.get("tangents_output_path"), "");
        result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        result.input_vertex_count = static_cast<int>(vertices.size());
        result.input_face_count = static_cast<int>(faces.size());
        if (result.index < 0 || vertices.empty() || faces.empty()) {
            continue;
        }

        std::vector<float> positions;
        positions.reserve(vertices.size() * 3);
        for (const Vec3& vertex : vertices) {
            positions.push_back(static_cast<float>(vertex[0]));
            positions.push_back(static_cast<float>(vertex[1]));
            positions.push_back(static_cast<float>(vertex[2]));
        }
        std::vector<uint32_t> indices;
        indices.reserve(faces.size() * 3);
        for (const auto& face : faces) {
            indices.push_back(static_cast<uint32_t>(face[0]));
            indices.push_back(static_cast<uint32_t>(face[1]));
            indices.push_back(static_cast<uint32_t>(face[2]));
        }

        xatlas::Atlas* atlas = xatlas::Create();
        xatlas::MeshDecl mesh_decl;
        mesh_decl.vertexPositionData = positions.data();
        mesh_decl.vertexPositionStride = sizeof(float) * 3;
        mesh_decl.vertexCount = static_cast<uint32_t>(vertices.size());
        mesh_decl.indexData = indices.data();
        mesh_decl.indexCount = static_cast<uint32_t>(indices.size());
        mesh_decl.indexFormat = xatlas::IndexFormat::UInt32;
        const xatlas::AddMeshError add_error = xatlas::AddMesh(atlas, mesh_decl);
        if (add_error == xatlas::AddMeshError::Success) {
            xatlas::ChartOptions chart_options;
            xatlas::PackOptions pack_options;
            pack_options.resolution = static_cast<uint32_t>(resolution);
            xatlas::Generate(atlas, chart_options, pack_options);
            if (atlas->meshCount > 0) {
                const xatlas::Mesh& mesh = atlas->meshes[0];
                result.output_vertex_count = static_cast<int>(mesh.vertexCount);
                result.output_face_count = static_cast<int>(mesh.indexCount / 3);
                result.chart_count = static_cast<int>(mesh.chartCount);
                result.uvs.reserve(mesh.vertexCount);
                result.vertex_remap.reserve(mesh.vertexCount);
                const double width = atlas->width > 0 ? static_cast<double>(atlas->width) : 1.0;
                const double height = atlas->height > 0 ? static_cast<double>(atlas->height) : 1.0;
                for (uint32_t i = 0; i < mesh.vertexCount; ++i) {
                    const xatlas::Vertex& vertex = mesh.vertexArray[i];
                    result.uvs.push_back({static_cast<double>(vertex.uv[0]) / width, static_cast<double>(vertex.uv[1]) / height});
                    result.vertex_remap.push_back(static_cast<int>(vertex.xref));
                }
                result.faces.reserve(mesh.indexCount / 3);
                for (uint32_t i = 0; i + 2 < mesh.indexCount; i += 3) {
                    result.faces.push_back({
                        static_cast<int>(mesh.indexArray[i]),
                        static_cast<int>(mesh.indexArray[i + 1]),
                        static_cast<int>(mesh.indexArray[i + 2]),
                    });
                }
                bool vertex_remap_identity = result.vertex_remap.size() == vertices.size();
                if (vertex_remap_identity) {
                    for (std::size_t vertex_index = 0; vertex_index < result.vertex_remap.size(); ++vertex_index) {
                        if (result.vertex_remap[vertex_index] != static_cast<int>(vertex_index)) {
                            vertex_remap_identity = false;
                            break;
                        }
                    }
                }
                result.topology_changed = result.output_vertex_count != result.input_vertex_count
                    || result.output_face_count != result.input_face_count
                    || !vertex_remap_identity
                    || result.faces != faces;
                const std::vector<Vec2> existing_uvs = mesh_uvs_from_item(item);
                if (result.topology_changed || existing_uvs.size() != static_cast<std::size_t>(result.input_vertex_count)) {
                    result.changed_vertices.reserve(result.uvs.size());
                    for (std::size_t vertex_index = 0; vertex_index < result.uvs.size(); ++vertex_index) {
                        result.changed_vertices.push_back(static_cast<int>(vertex_index));
                    }
                } else {
                    for (std::size_t vertex_index = 0; vertex_index < result.uvs.size(); ++vertex_index) {
                        const int old_index = vertex_index < result.vertex_remap.size() ? result.vertex_remap[vertex_index] : -1;
                        if (old_index < 0
                            || static_cast<std::size_t>(old_index) >= existing_uvs.size()
                            || !same_vec2(existing_uvs[static_cast<std::size_t>(old_index)], result.uvs[vertex_index])) {
                            result.changed_vertices.push_back(static_cast<int>(vertex_index));
                        }
                    }
                }
                if (!result.vertex_remap.empty()) {
                    result.vertices = copy_values_by_vertex_remap(vertices, result.vertex_remap);
                    if (!result.normals_path.empty()) {
                        result.normals = copy_values_by_vertex_remap(mesh_normals_from_item(item), result.vertex_remap);
                        if (result.normals.size() != result.vertices.size() && result.vertices.size() == result.vertex_remap.size()) {
                            result.normals = compute_smooth_normals(result.vertices, result.faces);
                        }
                    }
                    if (!result.tangents_path.empty()) {
                        result.tangents = copy_values_by_vertex_remap(mesh_tangents_from_item(item), result.vertex_remap);
                    }
                    if (!result.tangent_signs_path.empty()) {
                        result.tangent_signs = copy_values_by_vertex_remap(mesh_tangent_signs_from_item(item), result.vertex_remap);
                    }
                    if (!result.bone_counts_path.empty() && !result.bone_indices_path.empty() && !result.bone_weights_path.empty()) {
                        result.bones = copy_bones_by_vertex_remap(mesh_bones_from_item(item), result.vertex_remap);
                    }
                    if (!result.source_vertex_map_path.empty()) {
                        std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
                            item,
                            "source_vertex_map_binary",
                            "source_vertex_map",
                            "source_vertex_map_start",
                            "source_vertex_map_count"
                        );
                        if (source_vertex_map.empty()) {
                            if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                                source_vertex_map = session->source_vertex_map;
                            }
                        }
                        result.source_vertex_map = copy_values_by_vertex_remap(source_vertex_map, result.vertex_remap);
                    }
                    if (!result.source_vertex_offsets_path.empty()) {
                        std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
                        if (source_vertex_offsets.empty()) {
                            if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
                                source_vertex_offsets = session->source_vertex_offsets;
                            }
                        }
                        result.source_vertex_offsets = copy_values_by_vertex_remap(source_vertex_offsets, result.vertex_remap);
                    }
                }
            }
        } else {
            result.status = "error";
            result.error = xatlas::StringForEnum(add_error);
        }
        xatlas::Destroy(atlas);
        results.push_back(std::move(result));
    }
    return results;
}

Vec3 add_vec3(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 sub_vec3(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 scale_vec3(const Vec3& value, double scale) {
    return {value[0] * scale, value[1] * scale, value[2] * scale};
}

double dot_vec3(const Vec3& left, const Vec3& right) {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

Vec3 normalized_vec3(const Vec3& value, const Vec3& fallback) {
    const double length = std::sqrt(dot_vec3(value, value));
    if (length > 1e-8 && std::isfinite(length)) {
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    return fallback;
}

double length_vec3(const Vec3& value) {
    return std::sqrt(dot_vec3(value, value));
}

std::vector<std::set<int>> build_vertex_adjacency(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces
) {
    std::vector<std::set<int>> adjacency(vertex_count);
    for (const auto& face : faces) {
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        adjacency[static_cast<std::size_t>(a)].insert(b);
        adjacency[static_cast<std::size_t>(a)].insert(c);
        adjacency[static_cast<std::size_t>(b)].insert(a);
        adjacency[static_cast<std::size_t>(b)].insert(c);
        adjacency[static_cast<std::size_t>(c)].insert(a);
        adjacency[static_cast<std::size_t>(c)].insert(b);
    }
    return adjacency;
}

std::vector<SubmeshSelectionResult> run_selection_edit(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const JsonValue* selection = root.get("selection");
    if (selection == nullptr || selection->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing selection object");
    }
    std::string operation = string_or(selection->get("operation"), "");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const int iterations = std::max(0, int_or(selection->get("iterations"), int_or(selection->get("steps"), 1)));
    const bool all_operation = operation == "all";
    const bool invert_operation = operation == "invert";
    std::vector<SubmeshSelectionResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        if (submesh_index < 0 || vertex_count == 0) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::set<int> selected = selected_vertices_from_edit_domains(item, vertex_count, faces);
        if (selected.empty() && !invert_operation && !all_operation) {
            continue;
        }
        if (all_operation) {
            selected.clear();
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                selected.insert(static_cast<int>(vertex_index));
            }
        } else if (invert_operation) {
            std::set<int> inverted;
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                if (selected.find(static_cast<int>(vertex_index)) == selected.end()) {
                    inverted.insert(static_cast<int>(vertex_index));
                }
            }
            selected = std::move(inverted);
        } else {
            const std::vector<std::set<int>> adjacency = build_vertex_adjacency(vertex_count, faces);
            for (int iteration = 0; iteration < iterations; ++iteration) {
                if (operation == "grow") {
                    std::set<int> next = selected;
                    for (const int vertex_index : selected) {
                        if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < adjacency.size()) {
                            next.insert(adjacency[static_cast<std::size_t>(vertex_index)].begin(), adjacency[static_cast<std::size_t>(vertex_index)].end());
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "shrink") {
                    std::set<int> next;
                    for (const int vertex_index : selected) {
                        if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= adjacency.size()) {
                            continue;
                        }
                        const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(vertex_index)];
                        bool keep = neighbors.empty();
                        if (!keep) {
                            keep = true;
                            for (const int neighbor : neighbors) {
                                if (selected.find(neighbor) == selected.end()) {
                                    keep = false;
                                    break;
                                }
                            }
                        }
                        if (keep) {
                            next.insert(vertex_index);
                        }
                    }
                    selected = std::move(next);
                } else if (operation == "smooth") {
                    std::set<int> next;
                    for (std::size_t vertex_index = 0; vertex_index < adjacency.size(); ++vertex_index) {
                        const std::set<int>& neighbors = adjacency[vertex_index];
                        const bool is_selected = selected.find(static_cast<int>(vertex_index)) != selected.end();
                        if (neighbors.empty()) {
                            if (is_selected) {
                                next.insert(static_cast<int>(vertex_index));
                            }
                            continue;
                        }
                        int selected_neighbors = 0;
                        for (const int neighbor : neighbors) {
                            if (selected.find(neighbor) != selected.end()) {
                                ++selected_neighbors;
                            }
                        }
                        const double ratio = static_cast<double>(selected_neighbors) / static_cast<double>(std::max<std::size_t>(1, neighbors.size()));
                        if ((is_selected && ratio >= 0.25) || (!is_selected && ratio >= 0.65)) {
                            next.insert(static_cast<int>(vertex_index));
                        }
                    }
                    selected = std::move(next);
                } else {
                    throw std::runtime_error("unsupported selection operation: " + operation);
                }
            }
        }
        if (!selected.empty()) {
            SubmeshSelectionResult result;
            result.index = submesh_index;
            result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
            result.selected_vertices.assign(selected.begin(), selected.end());
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<Vec2> vec2_array_from_json(const JsonValue* value) {
    std::vector<Vec2> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        Vec2 point{
            number_or(&item.array_value[0], 0.0),
            number_or(&item.array_value[1], 0.0),
        };
        if (std::isfinite(point[0]) && std::isfinite(point[1])) {
            result.push_back(point);
        }
    }
    return result;
}

bool uv_point_on_segment(const Vec2& point, const Vec2& left, const Vec2& right) {
    const double cross = (point[1] - left[1]) * (right[0] - left[0]) - (point[0] - left[0]) * (right[1] - left[1]);
    if (std::abs(cross) > 1.0e-9) {
        return false;
    }
    return std::min(left[0], right[0]) - 1.0e-9 <= point[0]
        && point[0] <= std::max(left[0], right[0]) + 1.0e-9
        && std::min(left[1], right[1]) - 1.0e-9 <= point[1]
        && point[1] <= std::max(left[1], right[1]) + 1.0e-9;
}

bool uv_point_in_polygon(const Vec2& point, const std::vector<Vec2>& polygon) {
    if (polygon.size() < 3) {
        return false;
    }
    bool inside = false;
    Vec2 previous = polygon.back();
    for (const Vec2& current : polygon) {
        if (uv_point_on_segment(point, previous, current)) {
            return true;
        }
        const bool crosses = (current[1] > point[1]) != (previous[1] > point[1]);
        if (crosses) {
            const double slope_x = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0];
            if (point[0] <= slope_x) {
                inside = !inside;
            }
        }
        previous = current;
    }
    return inside;
}

std::vector<SubmeshUvSelectionResult> run_uv_selection(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::string mode = string_or(root.get("mode"), "region");
    std::transform(mode.begin(), mode.end(), mode.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const Vec2 start = vec2_or(root.get("uv_min"), {0.0, 0.0});
    const Vec2 end = vec2_or(root.get("uv_max"), {0.0, 0.0});
    const double min_u = std::min(start[0], end[0]);
    const double max_u = std::max(start[0], end[0]);
    const double min_v = std::min(start[1], end[1]);
    const double max_v = std::max(start[1], end[1]);
    const std::vector<Vec2> polygon = vec2_array_from_json(root.get("points"));
    if (mode == "lasso" && polygon.size() < 3) {
        return {};
    }
    if (mode != "region" && mode != "lasso") {
        throw std::runtime_error("unsupported uv selection mode: " + mode);
    }

    std::vector<SubmeshUvSelectionResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (submesh_index < 0 || vertex_count == 0 || uvs.size() != vertex_count) {
            continue;
        }
        std::vector<int> selected;
        selected.reserve(uvs.size());
        for (std::size_t vertex_index = 0; vertex_index < uvs.size(); ++vertex_index) {
            const Vec2& uv = uvs[vertex_index];
            const bool contained = mode == "lasso"
                ? uv_point_in_polygon(uv, polygon)
                : (min_u <= uv[0] && uv[0] <= max_u && min_v <= uv[1] && uv[1] <= max_v);
            if (contained) {
                selected.push_back(static_cast<int>(vertex_index));
            }
        }
        if (selected.empty()) {
            continue;
        }
        SubmeshUvSelectionResult result;
        result.index = submesh_index;
        result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
        result.selected_vertices = std::move(selected);
        results.push_back(std::move(result));
    }
    return results;
}

using NativeUvKey = std::array<long long, 2>;
using NativeUvEdgeKey = std::tuple<std::array<int, 2>, NativeUvKey, NativeUvKey>;

NativeUvKey native_uv_key(const Vec2& value) {
    return {
        static_cast<long long>(std::llround(value[0] * 1000000.0)),
        static_cast<long long>(std::llround(value[1] * 1000000.0)),
    };
}

NativeUvEdgeKey native_uv_edge_key(int left, int right, const std::vector<Vec2>& uvs) {
    std::array<int, 2> vertex_edge{std::min(left, right), std::max(left, right)};
    NativeUvKey left_uv = native_uv_key(uvs[static_cast<std::size_t>(left)]);
    NativeUvKey right_uv = native_uv_key(uvs[static_cast<std::size_t>(right)]);
    if (right_uv < left_uv) {
        std::swap(left_uv, right_uv);
    }
    return std::make_tuple(vertex_edge, left_uv, right_uv);
}

std::vector<UvIslandSummaryResult> run_uv_summary(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<UvIslandSummaryResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (submesh_index < 0 || vertex_count == 0 || uvs.size() != vertex_count) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        if (faces.empty()) {
            continue;
        }
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
        std::set<int> selected_faces;
        for (const int face_index : int_vector_from_binary_or_json(
            item,
            "selected_faces_binary",
            "selected_faces",
            "selected_face_start",
            "selected_face_count"
        )) {
            if (face_index >= 0) {
                selected_faces.insert(face_index);
            }
        }
        const bool source_selected = bool_or(item.get("source_selected"), false);

        std::map<int, std::vector<NativeUvEdgeKey>> face_edges;
        std::map<NativeUvEdgeKey, std::set<int>> edge_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const std::array<int, 3>& face = faces[face_offset];
            std::vector<NativeUvEdgeKey> edges;
            edges.reserve(3);
            for (int edge_index = 0; edge_index < 3; ++edge_index) {
                const int left = face[static_cast<std::size_t>(edge_index)];
                const int right = face[static_cast<std::size_t>((edge_index + 1) % 3)];
                edges.push_back(native_uv_edge_key(left, right, uvs));
            }
            const int compact_face_index = static_cast<int>(face_offset);
            face_edges[compact_face_index] = edges;
            for (const NativeUvEdgeKey& edge : edges) {
                edge_faces[edge].insert(compact_face_index);
            }
        }

        std::set<int> visited;
        for (std::size_t seed_offset = 0; seed_offset < faces.size(); ++seed_offset) {
            const int seed = static_cast<int>(seed_offset);
            if (visited.find(seed) != visited.end()) {
                continue;
            }
            std::vector<int> pending{seed};
            std::set<int> island_faces;
            while (!pending.empty()) {
                const int face_index = pending.back();
                pending.pop_back();
                if (island_faces.find(face_index) != island_faces.end() || visited.find(face_index) != visited.end()) {
                    continue;
                }
                island_faces.insert(face_index);
                visited.insert(face_index);
                for (const NativeUvEdgeKey& edge : face_edges[face_index]) {
                    const std::set<int>& neighbors = edge_faces[edge];
                    for (const int neighbor : neighbors) {
                        if (island_faces.find(neighbor) == island_faces.end()) {
                            pending.push_back(neighbor);
                        }
                    }
                }
            }

            std::set<int> island_vertices;
            for (const int face_index : island_faces) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= faces.size()) {
                    continue;
                }
                const std::array<int, 3>& face = faces[static_cast<std::size_t>(face_index)];
                island_vertices.insert(face[0]);
                island_vertices.insert(face[1]);
                island_vertices.insert(face[2]);
            }
            if (island_vertices.empty()) {
                continue;
            }

            Vec2 uv_min{1.0e300, 1.0e300};
            Vec2 uv_max{-1.0e300, -1.0e300};
            int selected_vertex_count = 0;
            for (const int vertex_index : island_vertices) {
                const Vec2& uv = uvs[static_cast<std::size_t>(vertex_index)];
                uv_min[0] = std::min(uv_min[0], uv[0]);
                uv_min[1] = std::min(uv_min[1], uv[1]);
                uv_max[0] = std::max(uv_max[0], uv[0]);
                uv_max[1] = std::max(uv_max[1], uv[1]);
                if (selected_vertices.find(vertex_index) != selected_vertices.end()) {
                    ++selected_vertex_count;
                }
            }

            int selected_face_count = 0;
            for (const int face_index : island_faces) {
                const int source_face_index = static_cast<std::size_t>(face_index) < source_faces.size()
                    ? source_faces[static_cast<std::size_t>(face_index)]
                    : face_index;
                if (selected_faces.find(source_face_index) != selected_faces.end()) {
                    ++selected_face_count;
                }
            }

            UvIslandSummaryResult result;
            result.index = static_cast<int>(results.size());
            result.submesh_index = submesh_index;
            result.part_name = string_or(item.get("part_name"), std::string("part_") + std::to_string(submesh_index));
            result.material = string_or(item.get("material"), "");
            result.texture = string_or(item.get("texture"), "");
            result.vertex_count = static_cast<int>(island_vertices.size());
            result.face_count = static_cast<int>(island_faces.size());
            result.uv_min = uv_min;
            result.uv_max = uv_max;
            result.selected_vertex_count = selected_vertex_count;
            result.selected_face_count = selected_face_count;
            result.selected = source_selected || selected_vertex_count > 0 || selected_face_count > 0;
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<SubmeshMetadataResult> run_mesh_metadata(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMetadataResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshMetadataResult result;
        result.index = int_or(item.get("index"), -1);
        if (result.index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        result.vertex_count = vertices.empty()
            ? static_cast<std::size_t>(std::max(0, int_or(item.get("vertex_count"), 0)))
            : vertices.size();
        result.face_count = static_cast<std::size_t>(std::max(0, int_or(item.get("face_count"), 0)));
        if (item.get("faces_binary") != nullptr || item.get("faces") != nullptr || mesh_session_submesh_for_item(item) != nullptr) {
            result.face_count = mesh_faces_from_item(item, result.vertex_count).size();
        }
        const std::size_t explicit_uv_count = static_cast<std::size_t>(std::max(0, int_or(item.get("uv_count"), 0)));
        const bool explicit_has_uvs = bool_or(item.get("has_uvs"), false);
        if (item.get("uvs_binary") != nullptr || item.get("uvs") != nullptr || mesh_session_submesh_for_item(item) != nullptr) {
            result.has_uvs = mesh_uvs_from_item(item).size() == result.vertex_count && result.vertex_count > 0;
        } else {
            result.has_uvs = explicit_has_uvs || explicit_uv_count > 0;
        }
        if (!vertices.empty()) {
            result.has_bounds = true;
            result.bbox_min = vertices.front();
            result.bbox_max = vertices.front();
            for (const Vec3& vertex : vertices) {
                result.bbox_min[0] = std::min(result.bbox_min[0], vertex[0]);
                result.bbox_min[1] = std::min(result.bbox_min[1], vertex[1]);
                result.bbox_min[2] = std::min(result.bbox_min[2], vertex[2]);
                result.bbox_max[0] = std::max(result.bbox_max[0], vertex[0]);
                result.bbox_max[1] = std::max(result.bbox_max[1], vertex[1]);
                result.bbox_max[2] = std::max(result.bbox_max[2], vertex[2]);
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionBoundsResult> run_selection_bounds(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshSelectionBoundsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshSelectionBoundsResult result;
        result.index = int_or(item.get("index"), -1);
        if (result.index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (vertices.empty()) {
            results.push_back(std::move(result));
            continue;
        }
        const std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertices.size());
        for (const int vertex_index : selected_vertices) {
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= vertices.size()) {
                continue;
            }
            const Vec3& vertex = vertices[static_cast<std::size_t>(vertex_index)];
            if (!result.has_bounds) {
                result.bbox_min = vertex;
                result.bbox_max = vertex;
                result.has_bounds = true;
            } else {
                result.bbox_min[0] = std::min(result.bbox_min[0], vertex[0]);
                result.bbox_min[1] = std::min(result.bbox_min[1], vertex[1]);
                result.bbox_min[2] = std::min(result.bbox_min[2], vertex[2]);
                result.bbox_max[0] = std::max(result.bbox_max[0], vertex[0]);
                result.bbox_max[1] = std::max(result.bbox_max[1], vertex[1]);
                result.bbox_max[2] = std::max(result.bbox_max[2], vertex[2]);
            }
            ++result.selected_vertex_count;
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionPreviewResult> run_selection_preview(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshSelectionPreviewResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        if (submesh_index < 0 || vertex_count == 0) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (item.get("source_face_indices_binary") == nullptr
            && item.get("source_face_indices") == nullptr
            && item.get("source_face_start") == nullptr
            && item.get("faces") != nullptr) {
            const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
            if (raw_source_faces.size() == faces.size()) {
                source_faces = raw_source_faces;
            }
        }
        std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, vertex_count);
        const std::vector<int> selected_face_items = int_vector_from_binary_or_json(
            item,
            "selected_faces_binary",
            "selected_faces",
            "selected_face_start",
            "selected_face_count"
        );
        std::set<int> selected_faces;
        for (const int face_index : selected_face_items) {
            if (face_index >= 0) {
                selected_faces.insert(face_index);
            }
        }
        std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertex_count);
        if (!faces.empty() && !selected_edges.empty()) {
            const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
            std::set<std::array<int, 2>> kept_edges;
            for (const auto& edge : selected_edges) {
                if (existing_edges.find(edge) != existing_edges.end()) {
                    kept_edges.insert(edge);
                }
            }
            selected_edges = std::move(kept_edges);
        }
        if (bool_or(item.get("selected_all_vertices"), false)) {
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                selected_vertices.insert(static_cast<int>(vertex_index));
            }
        }
        for (const auto& edge : selected_edges) {
            selected_vertices.insert(edge[0]);
            selected_vertices.insert(edge[1]);
        }
        std::set<int> selected_source_faces;
        for (std::size_t face_offset = 0; face_offset < faces.size(); ++face_offset) {
            const int source_face_index = face_offset < source_faces.size()
                ? source_faces[face_offset]
                : static_cast<int>(face_offset);
            if (selected_faces.find(source_face_index) == selected_faces.end()) {
                continue;
            }
            selected_source_faces.insert(source_face_index);
            const auto& face = faces[face_offset];
            selected_vertices.insert(face[0]);
            selected_vertices.insert(face[1]);
            selected_vertices.insert(face[2]);
        }
        if (selected_vertices.empty()) {
            continue;
        }
        SubmeshSelectionPreviewResult result;
        result.index = submesh_index;
        result.source_vertex_indices.assign(selected_vertices.begin(), selected_vertices.end());
        result.source_face_indices.assign(selected_source_faces.begin(), selected_source_faces.end());
        result.source_edges.assign(selected_edges.begin(), selected_edges.end());
        result.selection_preview_path = string_or(item.get("selection_preview_output_path"), "");
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionPruneResult> run_selection_prune(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string root_selection_operation = normalized_selection_operation(
        string_or(root.get("selection_operation"), "replace")
    );
    std::vector<SubmeshSelectionPruneResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const std::string selection_operation = normalized_selection_operation(
            string_or(item.get("selection_operation"), root_selection_operation)
        );
        const int submesh_index = int_or(item.get("index"), -1);
        const std::size_t vertex_count = mesh_vertex_count_from_item(item);
        if (submesh_index < 0 || vertex_count == 0) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertex_count);
        std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (item.get("source_face_indices_binary") == nullptr
            && item.get("source_face_indices") == nullptr
            && item.get("source_face_start") == nullptr
            && item.get("faces") != nullptr) {
            const std::vector<int> raw_source_faces = source_face_indices_from_faces_json(item.get("faces"), vertex_count);
            if (raw_source_faces.size() == faces.size()) {
                source_faces = raw_source_faces;
            }
        }

        std::set<int> selected_vertices = combine_selection_sets(
            selected_vertices_from_binary_or_json_keys(
                item,
                vertex_count,
                "current_selected_vertices_binary",
                "current_selected_vertices",
                "current_selected_vertex_start",
                "current_selected_vertex_count"
            ),
            selected_vertices_from_binary_or_json(item, vertex_count),
            selection_operation
        );

        std::set<std::array<int, 2>> selected_edges = combine_selection_sets(
            selected_edges_from_binary_or_json_keys(
                item,
                vertex_count,
                "current_selected_edges_binary",
                "current_selected_edges"
            ),
            selected_edges_from_binary_or_json(item, vertex_count),
            selection_operation
        );
        if (!faces.empty() && !selected_edges.empty()) {
            const std::set<std::array<int, 2>> existing_edges = face_edge_set(faces);
            std::set<std::array<int, 2>> kept_edges;
            for (const auto& edge : selected_edges) {
                if (existing_edges.find(edge) != existing_edges.end()) {
                    kept_edges.insert(edge);
                }
            }
            selected_edges = std::move(kept_edges);
        }

        const int explicit_face_count = int_or(item.get("face_count"), static_cast<int>(faces.size()));
        const std::size_t selection_face_count = explicit_face_count > 0
            ? static_cast<std::size_t>(explicit_face_count)
            : faces.size();
        std::set<int> selected_faces = combine_selection_sets(
            selected_prune_faces_from_keys(
                item,
                "current_selected_faces_binary",
                "current_selected_faces",
                selection_face_count,
                faces,
                source_faces
            ),
            selected_prune_faces_from_keys(
                item,
                "selected_faces_binary",
                "selected_faces",
                selection_face_count,
                faces,
                source_faces
            ),
            selection_operation
        );

        if (selected_vertices.empty() && selected_edges.empty() && selected_faces.empty()) {
            continue;
        }
        SubmeshSelectionPruneResult result;
        result.index = submesh_index;
        result.selected_vertices.assign(selected_vertices.begin(), selected_vertices.end());
        result.selected_edges.assign(selected_edges.begin(), selected_edges.end());
        result.selected_faces.assign(selected_faces.begin(), selected_faces.end());
        result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "");
        result.selected_edges_path = string_or(item.get("selected_edges_output_path"), "");
        result.selected_faces_path = string_or(item.get("selected_faces_output_path"), "");
        results.push_back(std::move(result));
    }
    return results;
}

double brush_falloff_weight(double distance, double radius, const std::string& falloff) {
    if (radius <= 1e-8) {
        return distance <= 1e-8 ? 1.0 : 0.0;
    }
    const double normalized = std::max(0.0, std::min(1.0, distance / radius));
    if (normalized >= 1.0) {
        return 0.0;
    }
    if (falloff == "linear") {
        return 1.0 - normalized;
    }
    if (falloff == "sharp") {
        return (1.0 - normalized) * (1.0 - normalized);
    }
    if (falloff == "constant") {
        return 1.0;
    }
    const double t = normalized;
    return 1.0 - (t * t * (3.0 - 2.0 * t));
}

bool mesh_editor_screen_brush_submesh_allowed(const JsonValue& item, const JsonValue& brush) {
    const std::vector<int> indices = int_vector_from_json(brush.get("source_submesh_indices"));
    if (indices.empty()) {
        return true;
    }
    const int submesh_index = int_or(item.get("index"), -1);
    return std::find(indices.begin(), indices.end(), submesh_index) != indices.end();
}

struct MeshEditorScreenBrushProjection {
    double viewport_width = 1.0;
    double viewport_height = 1.0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    std::array<double, 16> camera_world{};
    std::array<double, 16> world_view_projection{};
    std::map<int, std::array<double, 16>> source_world_view_projections;
    std::set<int> source_projection_overrides;
    bool has_camera_world = false;
    bool has_world_view_projection = false;
    bool projection_payload_unresolved = false;
};

struct MeshEditorScreenRay {
    Vec3 origin{0.0, 0.0, 0.0};
    Vec3 direction{0.0, 0.0, 0.0};
};

MeshEditorScreenBrushProjection mesh_editor_screen_brush_projection(const JsonValue& brush) {
    MeshEditorScreenBrushProjection projection;
    projection.viewport_width = std::max(number_or(brush.get("viewport_width"), number_or(brush.get("width"), 0.0)), 1.0);
    projection.viewport_height = std::max(number_or(brush.get("viewport_height"), number_or(brush.get("height"), 0.0)), 1.0);
    projection.viewport_x = number_or(brush.get("viewport_x"), number_or(brush.get("top_left_x"), 0.0));
    projection.viewport_y = number_or(brush.get("viewport_y"), number_or(brush.get("top_left_y"), 0.0));
    projection.has_camera_world = matrix4x4_from_json(brush.get("camera_world"), projection.camera_world);
    projection.has_world_view_projection = matrix4x4_from_json(brush.get("world_view_projection"), projection.world_view_projection);
    projection.projection_payload_unresolved = brush.get("world_view_projection") != nullptr && !projection.has_world_view_projection;
    for (const char* key : {"source_submesh_world_view_projections", "source_world_view_projections"}) {
        const JsonValue* overrides = brush.get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            projection.projection_payload_unresolved = true;
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int source_submesh_index = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_view_projection{};
            if (source_submesh_index >= 0) {
                projection.source_projection_overrides.insert(source_submesh_index);
            }
            if (source_submesh_index >= 0
                && matrix4x4_from_json(item.get("world_view_projection"), source_world_view_projection)) {
                projection.source_world_view_projections[source_submesh_index] = source_world_view_projection;
            }
        }
    }
    for (const char* key : {"source_submesh_world_transforms", "source_world_transforms"}) {
        const JsonValue* overrides = brush.get(key);
        if (overrides == nullptr) {
            continue;
        }
        if (overrides->type != JsonValue::Type::Array) {
            projection.projection_payload_unresolved = true;
            continue;
        }
        for (const JsonValue& item : overrides->array_value) {
            const int source_submesh_index = mesh_editor_source_projection_override_index(item);
            std::array<double, 16> source_world_transform{};
            if (source_submesh_index >= 0) {
                projection.source_projection_overrides.insert(source_submesh_index);
            }
            if (source_submesh_index >= 0
                && projection.has_world_view_projection
                && projection.source_world_view_projections.find(source_submesh_index) == projection.source_world_view_projections.end()
                && matrix4x4_from_transform_json(item, source_world_transform)) {
                projection.source_world_view_projections[source_submesh_index] =
                    matrix4x4_multiply(source_world_transform, projection.world_view_projection);
            }
        }
    }
    if (!projection.has_world_view_projection && !projection.source_projection_overrides.empty()) {
        projection.projection_payload_unresolved = true;
    }
    return projection;
}

MeshEditorScreenBrushProjection mesh_editor_projection_for_submesh(
    const MeshEditorScreenBrushProjection& projection,
    int source_submesh_index
) {
    const auto found = projection.source_world_view_projections.find(source_submesh_index);
    if (found == projection.source_world_view_projections.end()) {
        if (projection.source_projection_overrides.find(source_submesh_index) != projection.source_projection_overrides.end()) {
            MeshEditorScreenBrushProjection scoped = projection;
            scoped.has_camera_world = false;
            scoped.has_world_view_projection = false;
            scoped.projection_payload_unresolved = true;
            return scoped;
        }
        return projection;
    }
    MeshEditorScreenBrushProjection scoped = projection;
    scoped.world_view_projection = found->second;
    scoped.has_world_view_projection = true;
    scoped.projection_payload_unresolved = false;
    return scoped;
}

bool mesh_editor_screen_ray_from_projection(
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection,
    MeshEditorScreenRay& ray
) {
    if (projection.projection_payload_unresolved || !projection.has_world_view_projection) {
        return false;
    }
    const double screen_x = number_or(brush.get("x"), number_or(brush.get("cursor_x"), number_or(brush.get("screen_x"), std::numeric_limits<double>::quiet_NaN())));
    const double screen_y = number_or(brush.get("y"), number_or(brush.get("cursor_y"), number_or(brush.get("screen_y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(screen_x) || !std::isfinite(screen_y)) {
        return false;
    }
    std::array<double, 16> inverse_matrix{};
    if (!matrix4x4_inverse(projection.world_view_projection, inverse_matrix)) {
        return false;
    }
    Vec3 near_point{};
    Vec3 far_point{};
    if (!unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            screen_x,
            screen_y,
            0.0,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            near_point)
        || !unproject_screen_point_with_matrix_inverse(
            inverse_matrix,
            screen_x,
            screen_y,
            1.0,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            far_point)) {
        return false;
    }
    const Vec3 direction = normalized_vec3(sub_vec3(far_point, near_point), {0.0, 0.0, 0.0});
    if (length_vec3(direction) <= 0.5) {
        return false;
    }
    ray.origin = near_point;
    ray.direction = direction;
    return true;
}

bool mesh_editor_project_screen_brush_vertex_with_matrix(
    const std::array<double, 16>& matrix,
    const Vec3& vertex,
    double viewport_x,
    double viewport_y,
    double viewport_width,
    double viewport_height,
    double& screen_x,
    double& screen_y
) {
    // Matches DirectX row-vector XMFLOAT4X4 layout from XMStoreFloat4x4.
    return project_vertex_with_matrix(matrix, vertex, viewport_x, viewport_y, viewport_width, viewport_height, screen_x, screen_y);
}

bool mesh_editor_project_screen_brush_vertex_with_projection(
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection,
    const Vec3& vertex,
    double& screen_x,
    double& screen_y,
    double* depth_z = nullptr
) {
    if (projection.projection_payload_unresolved) {
        return false;
    }
    if (projection.has_world_view_projection) {
        double projected_depth = 0.0;
        if (!project_vertex_with_matrix_depth(
            projection.world_view_projection,
            vertex,
            projection.viewport_x,
            projection.viewport_y,
            projection.viewport_width,
            projection.viewport_height,
            screen_x,
            screen_y,
            projected_depth
        )) {
            return false;
        }
        if (depth_z != nullptr) {
            *depth_z = projected_depth;
        }
        return true;
    }
    if (projection.projection_payload_unresolved) {
        return false;
    }
    const double distance = std::max(number_or(brush.get("distance"), 0.0), 0.1);
    const double fov = std::max(number_or(brush.get("vertical_fov_degrees"), 45.0), 1e-6);
    Vec3 world{};
    if (projection.has_camera_world) {
        const Vec3 right{projection.camera_world[0], projection.camera_world[1], projection.camera_world[2]};
        const Vec3 up{projection.camera_world[4], projection.camera_world[5], projection.camera_world[6]};
        const Vec3 forward{projection.camera_world[8], projection.camera_world[9], projection.camera_world[10]};
        const Vec3 origin{projection.camera_world[12], projection.camera_world[13], projection.camera_world[14]};
        world = {
            right[0] * vertex[0] + up[0] * vertex[1] + forward[0] * vertex[2] + origin[0],
            right[1] * vertex[0] + up[1] * vertex[1] + forward[1] * vertex[2] + origin[1],
            right[2] * vertex[0] + up[2] * vertex[1] + forward[2] * vertex[2] + origin[2],
        };
    } else {
        const double pitch = degrees_to_radians(number_or(brush.get("pitch_degrees"), number_or(brush.get("pitch"), 0.0)));
        const double yaw = degrees_to_radians(number_or(brush.get("yaw_degrees"), number_or(brush.get("yaw"), 0.0)));
        const Vec3 pan = vec3_or(brush.get("pan"), {
            number_or(brush.get("pan_x"), 0.0),
            number_or(brush.get("pan_y"), 0.0),
            number_or(brush.get("pan_z"), 0.0),
        });

        const double cp = std::cos(pitch);
        const double sp = std::sin(pitch);
        const double cy = std::cos(yaw);
        const double sy = std::sin(yaw);
        const Vec3 right{cy, sp * sy, cp * sy};
        const Vec3 up{0.0, cp, -sp};
        const Vec3 forward{-sy, sp * cy, cp * cy};
        world = {
            right[0] * vertex[0] + up[0] * vertex[1] + forward[0] * vertex[2] + pan[0],
            right[1] * vertex[0] + up[1] * vertex[1] + forward[1] * vertex[2] + pan[1],
            right[2] * vertex[0] + up[2] * vertex[1] + forward[2] * vertex[2] + pan[2],
        };
    }
    const double camera_z = world[2] + distance;
    if (!std::isfinite(camera_z) || camera_z < 0.05 || camera_z > 100.0) {
        return false;
    }
    const double tan_half_fov = std::tan(degrees_to_radians(fov) * 0.5);
    const double aspect = projection.viewport_width / projection.viewport_height;
    if (!std::isfinite(tan_half_fov) || std::abs(tan_half_fov) <= 1e-12 || !std::isfinite(aspect) || aspect <= 0.0) {
        return false;
    }
    const double clip_x = world[0] / (aspect * tan_half_fov * camera_z);
    const double clip_y = world[1] / (tan_half_fov * camera_z);
    if (!std::isfinite(clip_x) || !std::isfinite(clip_y)) {
        return false;
    }
    screen_x = projection.viewport_x + (clip_x * 0.5 + 0.5) * projection.viewport_width;
    screen_y = projection.viewport_y + (0.5 - clip_y * 0.5) * projection.viewport_height;
    if (depth_z != nullptr) {
        *depth_z = 0.0;
    }
    return std::isfinite(screen_x) && std::isfinite(screen_y);
}

bool mesh_editor_project_screen_brush_vertex(
    const JsonValue& brush,
    const Vec3& vertex,
    double& screen_x,
    double& screen_y
) {
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(brush);
    return mesh_editor_project_screen_brush_vertex_with_projection(brush, projection, vertex, screen_x, screen_y);
}

bool mesh_editor_ray_intersects_triangle(
    const MeshEditorScreenRay& ray,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    double& distance
) {
    auto cross = [](const Vec3& left, const Vec3& right) -> Vec3 {
        return {
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        };
    };
    const Vec3 edge1 = sub_vec3(b, a);
    const Vec3 edge2 = sub_vec3(c, a);
    const Vec3 pvec = cross(ray.direction, edge2);
    const double determinant = dot_vec3(edge1, pvec);
    if (!std::isfinite(determinant) || std::abs(determinant) <= 1e-10) {
        return false;
    }
    const double inverse_determinant = 1.0 / determinant;
    const Vec3 tvec = sub_vec3(ray.origin, a);
    const double u = dot_vec3(tvec, pvec) * inverse_determinant;
    if (u < -1e-8 || u > 1.0 + 1e-8) {
        return false;
    }
    const Vec3 qvec = cross(tvec, edge1);
    const double v = dot_vec3(ray.direction, qvec) * inverse_determinant;
    if (v < -1e-8 || u + v > 1.0 + 1e-8) {
        return false;
    }
    const double t = dot_vec3(edge2, qvec) * inverse_determinant;
    if (!std::isfinite(t) || t < 0.0) {
        return false;
    }
    distance = t;
    return true;
}

bool mesh_editor_ray_segment_distance(
    const MeshEditorScreenRay& ray,
    const Vec3& a,
    const Vec3& b,
    double& distance,
    Vec3& closest_segment_point
) {
    const Vec3 segment = sub_vec3(b, a);
    const double segment_length_sq = dot_vec3(segment, segment);
    if (!std::isfinite(segment_length_sq) || segment_length_sq <= 1e-16) {
        const double ray_t = std::max(0.0, dot_vec3(ray.direction, sub_vec3(a, ray.origin)));
        const Vec3 closest_ray = add_vec3(ray.origin, scale_vec3(ray.direction, ray_t));
        closest_segment_point = a;
        distance = length_vec3(sub_vec3(closest_ray, a));
        return std::isfinite(distance);
    }
    const Vec3 origin_to_a = sub_vec3(ray.origin, a);
    const double ray_a = dot_vec3(ray.direction, ray.direction);
    const double ray_segment = dot_vec3(ray.direction, segment);
    const double ray_origin_to_a = dot_vec3(ray.direction, origin_to_a);
    const double segment_origin_to_a = dot_vec3(segment, origin_to_a);
    const double denom = ray_a * segment_length_sq - ray_segment * ray_segment;
    double ray_t = 0.0;
    if (std::abs(denom) > 1e-12 && std::isfinite(denom)) {
        ray_t = std::max(0.0, (ray_segment * segment_origin_to_a - ray_origin_to_a * segment_length_sq) / denom);
    }
    double segment_t = (ray_segment * ray_t + segment_origin_to_a) / segment_length_sq;
    if (segment_t < 0.0) {
        segment_t = 0.0;
        ray_t = std::max(0.0, -ray_origin_to_a / std::max(ray_a, 1e-16));
    } else if (segment_t > 1.0) {
        segment_t = 1.0;
        ray_t = std::max(0.0, (ray_segment - ray_origin_to_a) / std::max(ray_a, 1e-16));
    }
    const Vec3 closest_ray = add_vec3(ray.origin, scale_vec3(ray.direction, ray_t));
    closest_segment_point = add_vec3(a, scale_vec3(segment, segment_t));
    distance = length_vec3(sub_vec3(closest_ray, closest_segment_point));
    return std::isfinite(distance)
        && std::isfinite(closest_segment_point[0])
        && std::isfinite(closest_segment_point[1])
        && std::isfinite(closest_segment_point[2]);
}

int mesh_editor_pick_source_with_screen_ray(
    const MeshEditorSession* session,
    const JsonValue& brush,
    const MeshEditorScreenBrushProjection& projection
) {
    if (session == nullptr) {
        return -1;
    }
    int best_source_index = -1;
    double best_distance = std::numeric_limits<double>::infinity();
    for (const auto& entry : session->submeshes) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        JsonValue index_value;
        index_value.type = JsonValue::Type::Number;
        index_value.number_value = static_cast<double>(entry.first);
        item.object_value["index"] = index_value;
        if (!mesh_editor_screen_brush_submesh_allowed(item, brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        MeshEditorScreenRay ray;
        if (!mesh_editor_screen_ray_from_projection(brush, entry_projection, ray)) {
            continue;
        }
        for (const std::array<int, 3>& face : entry.second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                continue;
            }
            double distance = 0.0;
            if (!mesh_editor_ray_intersects_triangle(
                    ray,
                    entry.second.vertices[static_cast<std::size_t>(face[0])],
                    entry.second.vertices[static_cast<std::size_t>(face[1])],
                    entry.second.vertices[static_cast<std::size_t>(face[2])],
                    distance)) {
                continue;
            }
            if (distance < best_distance) {
                best_distance = distance;
                best_source_index = entry.first;
            }
        }
    }
    return best_source_index;
}

double mesh_editor_screen_segment_distance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by
) {
    const double vx = bx - ax;
    const double vy = by - ay;
    const double length_sq = vx * vx + vy * vy;
    if (length_sq <= 1.0e-12) {
        return std::hypot(px - ax, py - ay);
    }
    const double t = std::clamp(((px - ax) * vx + (py - ay) * vy) / length_sq, 0.0, 1.0);
    const double closest_x = ax + vx * t;
    const double closest_y = ay + vy * t;
    return std::hypot(px - closest_x, py - closest_y);
}

double mesh_editor_screen_edge_function(double ax, double ay, double bx, double by, double cx, double cy) {
    return (cx - ax) * (by - ay) - (cy - ay) * (bx - ax);
}

double mesh_editor_screen_triangle_distance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by,
    double cx,
    double cy,
    double* out_w0 = nullptr,
    double* out_w1 = nullptr,
    double* out_w2 = nullptr
) {
    const double area = mesh_editor_screen_edge_function(ax, ay, bx, by, cx, cy);
    if (std::abs(area) > 1.0e-12) {
        const double w0 = mesh_editor_screen_edge_function(bx, by, cx, cy, px, py) / area;
        const double w1 = mesh_editor_screen_edge_function(cx, cy, ax, ay, px, py) / area;
        const double w2 = mesh_editor_screen_edge_function(ax, ay, bx, by, px, py) / area;
        if (out_w0 != nullptr) *out_w0 = w0;
        if (out_w1 != nullptr) *out_w1 = w1;
        if (out_w2 != nullptr) *out_w2 = w2;
        if (w0 >= -0.001 && w1 >= -0.001 && w2 >= -0.001) {
            return 0.0;
        }
    } else {
        if (out_w0 != nullptr) *out_w0 = 1.0;
        if (out_w1 != nullptr) *out_w1 = 0.0;
        if (out_w2 != nullptr) *out_w2 = 0.0;
    }
    return std::min({
        mesh_editor_screen_segment_distance(px, py, ax, ay, bx, by),
        mesh_editor_screen_segment_distance(px, py, bx, by, cx, cy),
        mesh_editor_screen_segment_distance(px, py, cx, cy, ax, ay),
    });
}

struct MeshEditorScreenBrushDepthMask {
    bool valid = false;
    int width = 0;
    int height = 0;
    double viewport_x = 0.0;
    double viewport_y = 0.0;
    double scale_x = 1.0;
    double scale_y = 1.0;
    std::vector<double> depths;
};

MeshEditorScreenBrushDepthMask mesh_editor_screen_brush_depth_mask(
    const MeshEditorSession* session,
    const JsonValue& brush
) {
    MeshEditorScreenBrushDepthMask mask;
    if (session == nullptr) {
        return mask;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(brush);
    if (!projection.has_world_view_projection && projection.source_world_view_projections.empty()) {
        return mask;
    }
    constexpr double kMaxDepthMaskDimension = 1024.0;
    const double scale = std::min(1.0, kMaxDepthMaskDimension / std::max(projection.viewport_width, projection.viewport_height));
    mask.valid = true;
    mask.width = std::max(1, static_cast<int>(std::ceil(projection.viewport_width * scale)));
    mask.height = std::max(1, static_cast<int>(std::ceil(projection.viewport_height * scale)));
    mask.viewport_x = projection.viewport_x;
    mask.viewport_y = projection.viewport_y;
    mask.scale_x = static_cast<double>(mask.width) / projection.viewport_width;
    mask.scale_y = static_cast<double>(mask.height) / projection.viewport_height;
    mask.depths.assign(
        static_cast<std::size_t>(mask.width) * static_cast<std::size_t>(mask.height),
        std::numeric_limits<double>::infinity()
    );

    auto rasterize_triangle = [&](const Vec3& p0, const Vec3& p1, const Vec3& p2) {
        const double area = mesh_editor_screen_edge_function(p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]);
        if (std::abs(area) <= 1.0e-12) {
            return;
        }
        int min_x = static_cast<int>(std::floor(std::min({p0[0], p1[0], p2[0]})));
        int max_x = static_cast<int>(std::ceil(std::max({p0[0], p1[0], p2[0]})));
        int min_y = static_cast<int>(std::floor(std::min({p0[1], p1[1], p2[1]})));
        int max_y = static_cast<int>(std::ceil(std::max({p0[1], p1[1], p2[1]})));
        min_x = std::max(0, std::min(mask.width - 1, min_x));
        max_x = std::max(0, std::min(mask.width - 1, max_x));
        min_y = std::max(0, std::min(mask.height - 1, min_y));
        max_y = std::max(0, std::min(mask.height - 1, max_y));
        if (min_x > max_x || min_y > max_y) {
            return;
        }
        for (int py = min_y; py <= max_y; ++py) {
            const double y = static_cast<double>(py) + 0.5;
            for (int px = min_x; px <= max_x; ++px) {
                const double x = static_cast<double>(px) + 0.5;
                const double w0 = mesh_editor_screen_edge_function(p1[0], p1[1], p2[0], p2[1], x, y) / area;
                const double w1 = mesh_editor_screen_edge_function(p2[0], p2[1], p0[0], p0[1], x, y) / area;
                const double w2 = mesh_editor_screen_edge_function(p0[0], p0[1], p1[0], p1[1], x, y) / area;
                if (w0 < -0.001 || w1 < -0.001 || w2 < -0.001) {
                    continue;
                }
                const double depth = w0 * p0[2] + w1 * p1[2] + w2 * p2[2];
                if (!std::isfinite(depth)) {
                    continue;
                }
                const std::size_t offset = static_cast<std::size_t>(py) * static_cast<std::size_t>(mask.width)
                    + static_cast<std::size_t>(px);
                mask.depths[offset] = std::min(mask.depths[offset], depth);
            }
        }
    };

    for (const auto& entry : session->submeshes) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        JsonValue index_value;
        index_value.type = JsonValue::Type::Number;
        index_value.number_value = static_cast<double>(entry.first);
        item.object_value["index"] = index_value;
        if (!mesh_editor_screen_brush_submesh_allowed(item, brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        for (const std::array<int, 3>& face : entry.second.faces) {
            if (face[0] < 0 || face[1] < 0 || face[2] < 0
                || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                continue;
            }
            Vec3 projected[3]{};
            bool valid = true;
            for (int corner = 0; corner < 3; ++corner) {
                double screen_x = 0.0;
                double screen_y = 0.0;
                double depth_z = 0.0;
                if (!mesh_editor_project_screen_brush_vertex_with_projection(
                        brush,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[static_cast<std::size_t>(corner)])],
                        screen_x,
                        screen_y,
                        &depth_z)) {
                    valid = false;
                    break;
                }
                projected[corner] = {
                    (screen_x - mask.viewport_x) * mask.scale_x,
                    (screen_y - mask.viewport_y) * mask.scale_y,
                    depth_z,
                };
            }
            if (valid) {
                rasterize_triangle(projected[0], projected[1], projected[2]);
            }
        }
    }
    return mask;
}

bool mesh_editor_screen_brush_depth_visible(
    const MeshEditorScreenBrushDepthMask* mask,
    double screen_x,
    double screen_y,
    double depth_z
) {
    if (mask == nullptr || !mask->valid || mask->width <= 0 || mask->height <= 0 || mask->depths.empty()) {
        return true;
    }
    const int x = static_cast<int>(std::floor((screen_x - mask->viewport_x) * mask->scale_x));
    const int y = static_cast<int>(std::floor((screen_y - mask->viewport_y) * mask->scale_y));
    if (x < 0 || y < 0 || x >= mask->width || y >= mask->height) {
        return false;
    }
    const std::size_t offset = static_cast<std::size_t>(y) * static_cast<std::size_t>(mask->width)
        + static_cast<std::size_t>(x);
    if (offset >= mask->depths.size()) {
        return true;
    }
    const double front_depth = mask->depths[offset];
    if (!std::isfinite(front_depth) || !std::isfinite(depth_z)) {
        return true;
    }
    return depth_z <= front_depth + 0.0035;
}

std::map<int, double> screen_brush_vertex_weights_native(
    const JsonValue& item,
    const std::vector<Vec3>& vertices,
    const std::set<int>* allowed,
    const std::string& falloff,
    const JsonValue* raw_brush,
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr
) {
    std::map<int, double> weights;
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return weights;
    }
    const JsonValue* raw_x = raw_brush->get("x");
    if (raw_x == nullptr) raw_x = raw_brush->get("cursor_x");
    if (raw_x == nullptr) raw_x = raw_brush->get("screen_x");
    const JsonValue* raw_y = raw_brush->get("y");
    if (raw_y == nullptr) raw_y = raw_brush->get("cursor_y");
    if (raw_y == nullptr) raw_y = raw_brush->get("screen_y");
    if (raw_x == nullptr || raw_y == nullptr || !mesh_editor_screen_brush_submesh_allowed(item, *raw_brush)) {
        return weights;
    }
    const double cursor_x = number_or(raw_x, 0.0);
    const double cursor_y = number_or(raw_y, 0.0);
    const double radius_pixels = std::max(
        0.0,
        number_or(raw_brush->get("radius_pixels"), number_or(raw_brush->get("brush_radius_pixels"), number_or(raw_brush->get("pixels"), 0.0)))
    );
    if (!std::isfinite(cursor_x) || !std::isfinite(cursor_y) || radius_pixels <= 1e-8) {
        return weights;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_brush);
    const int source_submesh_index = int_or(item.get("index"), -1);
    const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, source_submesh_index);
    auto add_weight = [&](int index) {
        if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
            return;
        }
        double screen_x = 0.0;
        double screen_y = 0.0;
        double depth_z = 0.0;
        if (!mesh_editor_project_screen_brush_vertex_with_projection(
                *raw_brush,
                entry_projection,
                vertices[static_cast<std::size_t>(index)],
                screen_x,
                screen_y,
                depth_mask != nullptr ? &depth_z : nullptr)) {
            return;
        }
        if (!mesh_editor_screen_brush_depth_visible(depth_mask, screen_x, screen_y, depth_z)) {
            return;
        }
        const double distance_pixels = std::hypot(cursor_x - screen_x, cursor_y - screen_y);
        if (distance_pixels > radius_pixels) {
            return;
        }
        const double weight = std::max(
            distance_pixels <= 1e-8 ? 1.0 : 0.0,
            brush_falloff_weight(distance_pixels, radius_pixels, falloff)
        );
        if (weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    };
    if (allowed != nullptr) {
        for (const int index : *allowed) {
            add_weight(index);
        }
        return weights;
    }
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        add_weight(static_cast<int>(index));
    }
    return weights;
}

bool mesh_editor_screen_brush_projection_unresolved_for_item(const JsonValue& item, const JsonValue* raw_brush) {
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return false;
    }
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_brush);
    const int source_submesh_index = int_or(item.get("index"), -1);
    return mesh_editor_projection_for_submesh(projection, source_submesh_index).projection_payload_unresolved;
}

const MeshEditorScreenBrushDepthMask* mesh_editor_screen_brush_depth_mask_for_edit(
    const JsonValue& item,
    const JsonValue& edit,
    const JsonValue* raw_brush,
    MeshEditorScreenBrushDepthMask& storage
) {
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return nullptr;
    }
    const std::string depth_mode = lower_ascii(string_or(
        edit.get("selection_depth_mode"),
        string_or(edit.get("depth_mode"), string_or(raw_brush->get("selection_depth_mode"), string_or(raw_brush->get("depth_mode"), "xray")))
    ));
    if (depth_mode == "xray") {
        return nullptr;
    }
    const MeshEditorSession* session = mesh_editor_session_for_item(item);
    if (session == nullptr) {
        return nullptr;
    }
    storage = mesh_editor_screen_brush_depth_mask(session, *raw_brush);
    return storage.valid ? &storage : nullptr;
}

std::map<int, int> mirror_pairs_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::map<int, int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int left = int_or(&item.array_value[0], -1);
        const int right = int_or(&item.array_value[1], -1);
        if (left >= 0 && right >= 0
            && static_cast<std::size_t>(left) < vertex_count
            && static_cast<std::size_t>(right) < vertex_count) {
            result[left] = right;
        }
    }
    return result;
}

std::map<int, int> build_x_mirror_pairs_native(const std::vector<Vec3>& vertices) {
    std::map<std::array<long long, 3>, std::vector<int>> buckets;
    const double scale = 10000.0;
    for (std::size_t i = 0; i < vertices.size(); ++i) {
        const Vec3& vertex = vertices[i];
        const std::array<long long, 3> key{
            static_cast<long long>(std::llround(vertex[0] * scale)),
            static_cast<long long>(std::llround(vertex[1] * scale)),
            static_cast<long long>(std::llround(vertex[2] * scale)),
        };
        buckets[key].push_back(static_cast<int>(i));
    }
    std::map<int, int> pairs;
    for (std::size_t i = 0; i < vertices.size(); ++i) {
        const Vec3& vertex = vertices[i];
        const std::array<long long, 3> mirror_key{
            static_cast<long long>(std::llround(-vertex[0] * scale)),
            static_cast<long long>(std::llround(vertex[1] * scale)),
            static_cast<long long>(std::llround(vertex[2] * scale)),
        };
        const auto found = buckets.find(mirror_key);
        if (found == buckets.end() || found->second.empty()) {
            continue;
        }
        const Vec3 expected{-vertex[0], vertex[1], vertex[2]};
        int best = found->second.front();
        double best_distance = distance_squared_vec3(vertices[static_cast<std::size_t>(best)], expected);
        for (const int candidate : found->second) {
            const double distance = distance_squared_vec3(vertices[static_cast<std::size_t>(candidate)], expected);
            if (distance < best_distance) {
                best = candidate;
                best_distance = distance;
            }
        }
        pairs[static_cast<int>(i)] = best;
    }
    return pairs;
}

std::map<int, double> vertex_weights_from_json(
    const JsonValue* value,
    std::size_t vertex_count,
    const std::set<int>* allowed
) {
    std::map<int, double> weights;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return weights;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        const int index = int_or(&item.array_value[0], -1);
        const double weight = std::max(0.0, std::min(1.0, number_or(&item.array_value[1], 0.0)));
        if (index < 0 || static_cast<std::size_t>(index) >= vertex_count || weight <= 0.0) {
            continue;
        }
        if (allowed != nullptr && allowed->find(index) == allowed->end()) {
            continue;
        }
        weights[index] = std::max(weights[index], weight);
    }
    return weights;
}

std::map<int, double> vertex_weights_from_edit(
    const JsonValue& edit,
    std::size_t vertex_count,
    const std::set<int>* allowed
) {
    std::map<int, double> weights;
    const JsonValue* binary_indices = edit.get("vertex_weight_indices_binary");
    const JsonValue* binary_weights = edit.get("vertex_weights_binary");
    if (binary_indices != nullptr || binary_weights != nullptr) {
        if (binary_indices == nullptr || binary_weights == nullptr) {
            return weights;
        }
        const std::vector<int> indices = int_vector_from_binary(binary_indices);
        const std::vector<double> values = double_vector_from_f32_or_f64_binary(binary_weights);
        if (indices.size() != values.size()) {
            return weights;
        }
        for (std::size_t offset = 0; offset < indices.size(); ++offset) {
            const int index = indices[offset];
            const double weight = std::max(0.0, std::min(1.0, values[offset]));
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count || weight <= 0.0) {
                continue;
            }
            if (allowed != nullptr && allowed->find(index) == allowed->end()) {
                continue;
            }
            weights[index] = std::max(weights[index], weight);
        }
        return weights;
    }
    return vertex_weights_from_json(edit.get("vertex_weights"), vertex_count, allowed);
}

std::map<int, double> affected_vertex_weights_native(
    const JsonValue& item,
    const std::vector<Vec3>& vertices,
    const Vec3& center,
    double radius,
    const std::string& falloff,
    const std::set<int>* allowed,
    const JsonValue& edit
) {
    const bool has_explicit_weights = edit.get("vertex_weights") != nullptr
        || edit.get("vertex_weight_indices_binary") != nullptr
        || edit.get("vertex_weights_binary") != nullptr;
    std::map<int, double> weights = vertex_weights_from_edit(edit, vertices.size(), allowed);
    if (!weights.empty() || has_explicit_weights) {
        return weights;
    }
    const JsonValue* raw_screen_brush = edit.get("screen_brush");
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = mesh_editor_screen_brush_depth_mask_for_edit(
        item,
        edit,
        raw_screen_brush,
        depth_mask_storage
    );
    const std::string stroke_phase = lower_ascii(string_or(edit.get("stroke_phase"), ""));
    const std::string target_mode = lower_ascii(string_or(edit.get("target_mode"), ""));
    const bool prefer_screen_brush = raw_screen_brush != nullptr
        && (stroke_phase == "update" || stroke_phase == "end" || target_mode != "selection");
    const bool screen_brush_projection_payload = mesh_editor_has_projection_payload(
        raw_screen_brush,
        int_or(item.get("index"), -1)
    );
    if (prefer_screen_brush) {
        weights = screen_brush_vertex_weights_native(item, vertices, allowed, falloff, raw_screen_brush, depth_mask);
        if (!weights.empty() || screen_brush_projection_payload) {
            return weights;
        }
        if (mesh_editor_screen_brush_projection_unresolved_for_item(item, raw_screen_brush)) {
            return weights;
        }
    }
    bool has_selection_weights = false;
    weights = selected_vertex_weights_from_editor_session(item, vertices.size(), allowed, has_selection_weights);
    if (!weights.empty() || has_selection_weights) {
        return weights;
    }
    weights = screen_brush_vertex_weights_native(item, vertices, allowed, falloff, raw_screen_brush, depth_mask);
    if (!weights.empty() || screen_brush_projection_payload) {
        return weights;
    }
    if (mesh_editor_screen_brush_projection_unresolved_for_item(item, raw_screen_brush)) {
        return weights;
    }
    if (allowed != nullptr) {
        for (const int index : *allowed) {
            if (index < 0 || static_cast<std::size_t>(index) >= vertices.size()) {
                continue;
            }
            double weight = brush_falloff_weight(length_vec3(sub_vec3(vertices[static_cast<std::size_t>(index)], center)), radius, falloff);
            if (radius <= 1e-8) {
                weight = 1.0;
            }
            if (weight > 0.0 || allowed->find(index) != allowed->end()) {
                weights[index] = std::max(weight, weights[index]);
            }
        }
        return weights;
    }
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        const double weight = brush_falloff_weight(length_vec3(sub_vec3(vertices[index], center)), radius, falloff);
        if (weight > 0.0) {
            weights[static_cast<int>(index)] = weight;
        }
    }
    return weights;
}

std::map<int, std::pair<double, bool>> with_mirror_weights_native(
    const std::vector<Vec3>& vertices,
    const std::map<int, double>& weights,
    bool mirror_x,
    std::map<int, int> mirror_pairs
) {
    std::map<int, std::pair<double, bool>> result;
    for (const auto& item : weights) {
        if (item.first >= 0 && static_cast<std::size_t>(item.first) < vertices.size() && item.second > 0.0) {
            result[item.first] = {item.second, false};
        }
    }
    if (!mirror_x) {
        return result;
    }
    if (mirror_pairs.empty()) {
        mirror_pairs = build_x_mirror_pairs_native(vertices);
    }
    for (const auto& item : result) {
        const auto found = mirror_pairs.find(item.first);
        if (found == mirror_pairs.end()) {
            continue;
        }
        const int mirror_index = found->second;
        const auto existing = result.find(mirror_index);
        if (existing == result.end() || item.second.first > existing->second.first) {
            result[mirror_index] = {item.second.first, true};
        }
    }
    return result;
}

SubmeshMeshEditResult run_brush_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "brush";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        return result;
    }

    const std::string tool = string_or(edit.get("tool"), "grab");
    const JsonValue* screen_radius_payload = edit.get("screen_radius");
    const bool screen_radius_projection_payload = mesh_editor_has_projection_payload(screen_radius_payload, result.index);
    const bool has_center = edit.get("center") != nullptr && !screen_radius_projection_payload;
    Vec3 center = has_center ? vec3_or(edit.get("center"), {0.0, 0.0, 0.0}) : Vec3{0.0, 0.0, 0.0};
    const double initial_screen_radius = screen_radius_projection_payload
        ? 0.0
        : (has_center
            ? mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index)
            : mesh_editor_screen_radius_units(screen_radius_payload));
    double radius = std::max(
        screen_radius_projection_payload
            ? 1.0
            : number_or(edit.get("radius"), initial_screen_radius > 0.0 ? initial_screen_radius : 1.0),
        1e-8
    );
    const double strength = std::max(0.0, std::min(1.0, number_or(edit.get("strength"), 1.0)));
    std::string falloff = string_or(edit.get("falloff"), "smooth");
    std::transform(falloff.begin(), falloff.end(), falloff.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const bool mirror_x = bool_or(edit.get("mirror_x"), false);
    const bool invert = bool_or(edit.get("invert"), false);
    const bool sparse_output = bool_or(item.get("sparse_output"), bool_or(edit.get("sparse_output"), false));
    const int iterations = std::max(1, std::min(12, int_or(edit.get("iterations"), 1)));

    std::set<int> selected = selected_vertices_from_edit_domains(item, result.vertices.size(), faces);
    const bool restrict_selection = bool_or(item.get("selection_restricts_vertices"), false);
    const std::set<int>* allowed = restrict_selection ? &selected : nullptr;
    const std::map<int, double> direct_weights = affected_vertex_weights_native(
        item,
        result.vertices,
        center,
        radius,
        falloff,
        allowed,
        edit
    );
    if (!has_center && !direct_weights.empty()) {
        Vec3 weighted_center{0.0, 0.0, 0.0};
        double total_weight = 0.0;
        for (const auto& weight : direct_weights) {
            const int index = weight.first;
            if (index < 0 || static_cast<std::size_t>(index) >= result.vertices.size()) {
                continue;
            }
            const double clamped_weight = std::max(0.0, std::min(1.0, weight.second));
            if (clamped_weight <= 0.0) {
                continue;
            }
            weighted_center = add_vec3(weighted_center, scale_vec3(result.vertices[static_cast<std::size_t>(index)], clamped_weight));
            total_weight += clamped_weight;
        }
        if (total_weight > 1e-8) {
            center = scale_vec3(weighted_center, 1.0 / total_weight);
        }
    }
    const double screen_radius = mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index);
    if (screen_radius_projection_payload) {
        if (screen_radius <= 0.0) {
            result.vertices.clear();
            return result;
        }
        radius = std::max(screen_radius, 1e-8);
    }
    const JsonValue* screen_drag_payload = edit.get("screen_drag");
    const bool screen_drag_projection_payload = mesh_editor_has_projection_payload(screen_drag_payload, result.index);
    const Vec3 drag_base = screen_drag_projection_payload
        ? Vec3{0.0, 0.0, 0.0}
        : vec3_or(edit.get("drag_delta"), vec3_or(edit.get("delta"), {0.0, 0.0, 0.0}));
    const Vec3 drag_delta = add_screen_drag_delta(
        drag_base,
        screen_drag_payload,
        &center,
        result.index
    );
    double amount = screen_radius_projection_payload ? 0.0 : number_or(edit.get("amount"), 0.0);
    if (std::abs(amount) <= 1e-8) {
        if ((tool == "inflate" || tool == "pinch") && screen_radius > 1e-8) {
            const double amount_scale = number_or(screen_radius_payload->get("amount_scale"), 0.08);
            amount = screen_radius * amount_scale;
        } else {
            amount = length_vec3(drag_delta);
        }
    }
    amount *= strength;
    const std::map<int, std::pair<double, bool>> weighted = with_mirror_weights_native(
        result.vertices,
        direct_weights,
        mirror_x,
        mirror_pairs_from_json(item.get("mirror_pairs"), result.vertices.size())
    );
    if (weighted.empty()) {
        result.vertices.clear();
        return result;
    }

    const std::vector<Vec3> original = result.vertices;
    std::vector<Vec3> next = original;
    if (tool == "smooth") {
        std::vector<Vec3> relax = original;
        const std::vector<std::set<int>> adjacency = build_vertex_adjacency(original.size(), faces);
        for (int iteration = 0; iteration < iterations; ++iteration) {
            std::vector<Vec3> iteration_next = relax;
            for (const auto& item_weight : weighted) {
                const int index = item_weight.first;
                if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) {
                    continue;
                }
                const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(index)];
                if (neighbors.empty()) {
                    continue;
                }
                Vec3 sum{0.0, 0.0, 0.0};
                int count = 0;
                for (const int neighbor : neighbors) {
                    if (neighbor < 0 || static_cast<std::size_t>(neighbor) >= relax.size()) {
                        continue;
                    }
                    sum = add_vec3(sum, relax[static_cast<std::size_t>(neighbor)]);
                    ++count;
                }
                if (count <= 0) {
                    continue;
                }
                const Vec3 avg = scale_vec3(sum, 1.0 / static_cast<double>(count));
                const Vec3 vertex = relax[static_cast<std::size_t>(index)];
                const double blend = std::max(0.0, std::min(1.0, item_weight.second.first * strength));
                iteration_next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(sub_vec3(avg, vertex), blend));
            }
            relax = std::move(iteration_next);
        }
        next = relax;
    } else {
        std::vector<Vec3> normals = vertices_from_binary_or_json(item, "normals_binary", "normals");
        if (tool == "inflate" && normals.size() != original.size()) {
            normals = compute_smooth_normals(original, faces);
        }
        for (const auto& item_weight : weighted) {
            const int index = item_weight.first;
            if (index < 0 || static_cast<std::size_t>(index) >= original.size()) {
                continue;
            }
            const double weight = item_weight.second.first;
            const bool mirrored = item_weight.second.second;
            const Vec3 vertex = original[static_cast<std::size_t>(index)];
            const Vec3 applied_delta = mirrored ? Vec3{-drag_delta[0], drag_delta[1], drag_delta[2]} : drag_delta;
            if (tool == "grab") {
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(applied_delta, weight * strength));
            } else if (tool == "inflate") {
                const Vec3 fallback = normalized_vec3(sub_vec3(vertex, center), {0.0, 1.0, 0.0});
                const Vec3 normal = normalized_vec3(normals[static_cast<std::size_t>(index)], fallback);
                const double signed_amount = invert ? -amount : amount;
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(normal, signed_amount * weight));
            } else if (tool == "pinch") {
                const Vec3 local_center = mirrored ? Vec3{-center[0], center[1], center[2]} : center;
                const Vec3 direction = normalized_vec3(sub_vec3(local_center, vertex), {0.0, 0.0, 0.0});
                const double signed_amount = invert ? -std::abs(amount) : std::abs(amount);
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(direction, signed_amount * weight));
            } else {
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(applied_delta, weight * strength));
            }
        }
    }

    for (const auto& item_weight : weighted) {
        const int index = item_weight.first;
        if (index >= 0
            && static_cast<std::size_t>(index) < original.size()
            && !same_vec3(original[static_cast<std::size_t>(index)], next[static_cast<std::size_t>(index)])) {
            result.changed_vertices.push_back(index);
        }
    }
    if (result.changed_vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    result.vertices = std::move(next);
    if (sparse_output) {
        result.sparse = true;
        result.changed_positions.reserve(result.changed_vertices.size());
        result.before_positions.reserve(result.changed_vertices.size());
        for (const int index : result.changed_vertices) {
            if (index >= 0 && static_cast<std::size_t>(index) < result.vertices.size()) {
                result.changed_positions.push_back(result.vertices[static_cast<std::size_t>(index)]);
                result.before_positions.push_back(original[static_cast<std::size_t>(index)]);
            }
        }
    }
    return result;
}

SubmeshMeshEditResult run_delete_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "delete";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (result.index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
    if (selected_faces.empty()) {
        return result;
    }
    const bool remove_orphans = bool_or(edit.get("remove_orphans"), true);
    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        kept_faces.push_back(faces[face_index]);
        kept_source_faces.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }
    if (result.removed_faces <= 0) {
        return result;
    }
    if (!remove_orphans) {
        result.vertices = vertices;
        result.faces = std::move(kept_faces);
        result.source_face_indices = std::move(kept_source_faces);
        result.copy_vertex_indices.resize(vertices.size());
        result.index_map.resize(vertices.size());
        for (std::size_t i = 0; i < vertices.size(); ++i) {
            result.copy_vertex_indices[i] = static_cast<int>(i);
            result.index_map[i] = static_cast<int>(i);
        }
        result.topology_changed = true;
        return result;
    }
    std::set<int> used_vertices;
    for (const auto& face : kept_faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    std::map<int, int> index_map;
    for (const int old_index : used_vertices) {
        index_map[old_index] = static_cast<int>(result.vertices.size());
        result.vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }
    for (std::size_t kept_index = 0; kept_index < kept_faces.size(); ++kept_index) {
        const auto& face = kept_faces[kept_index];
        const auto a = index_map.find(face[0]);
        const auto b = index_map.find(face[1]);
        const auto c = index_map.find(face[2]);
        if (a != index_map.end() && b != index_map.end() && c != index_map.end()) {
            result.faces.push_back({a->second, b->second, c->second});
            result.source_face_indices.push_back(
                kept_index < kept_source_faces.size()
                    ? kept_source_faces[kept_index]
                    : static_cast<int>(kept_index)
            );
        }
    }
    result.index_map.assign(vertices.size(), -1);
    for (const auto& item_map : index_map) {
        result.index_map[static_cast<std::size_t>(item_map.first)] = item_map.second;
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_dissolve_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "dissolve";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (result.index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, vertices.size());
    if (!selected_edges.empty()) {
        std::map<std::array<int, 2>, std::vector<int>> edge_faces;
        for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
            const auto& face = faces[face_index];
            edge_faces[edge_key(face[0], face[1])].push_back(static_cast<int>(face_index));
            edge_faces[edge_key(face[1], face[2])].push_back(static_cast<int>(face_index));
            edge_faces[edge_key(face[2], face[0])].push_back(static_cast<int>(face_index));
        }

        bool internal_edges = true;
        for (const auto& edge : selected_edges) {
            if (edge_faces[edge].size() != 2) {
                internal_edges = false;
                break;
            }
        }

        std::map<int, std::array<int, 3>> replacements;
        std::set<int> used_faces;
        if (internal_edges) {
            for (const auto& edge : selected_edges) {
                const std::vector<int>& face_indices = edge_faces[edge];
                if (used_faces.find(face_indices[0]) != used_faces.end()
                    || used_faces.find(face_indices[1]) != used_faces.end()) {
                    replacements.clear();
                    internal_edges = false;
                    break;
                }
                const int left = edge[0];
                const int right = edge[1];
                const std::array<int, 3>& first_face = faces[static_cast<std::size_t>(face_indices[0])];
                const std::array<int, 3>& second_face = faces[static_cast<std::size_t>(face_indices[1])];
                int first_opposite = -1;
                int second_opposite = -1;
                for (const int index : first_face) {
                    if (index != left && index != right) {
                        first_opposite = index;
                        break;
                    }
                }
                for (const int index : second_face) {
                    if (index != left && index != right) {
                        second_opposite = index;
                        break;
                    }
                }
                if (first_opposite < 0 || second_opposite < 0 || first_opposite == second_opposite) {
                    replacements.clear();
                    internal_edges = false;
                    break;
                }
                const int lower = std::min(face_indices[0], face_indices[1]);
                const int upper = std::max(face_indices[0], face_indices[1]);
                replacements[lower] = {first_opposite, left, second_opposite};
                replacements[upper] = {first_opposite, second_opposite, right};
                used_faces.insert(face_indices[0]);
                used_faces.insert(face_indices[1]);
            }
        }

        if (internal_edges && !replacements.empty()) {
            result.vertices = vertices;
            result.faces.reserve(faces.size());
            result.source_face_indices.reserve(faces.size());
            for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
                const auto found = replacements.find(static_cast<int>(face_index));
                result.faces.push_back(found != replacements.end() ? found->second : faces[face_index]);
                result.source_face_indices.push_back(source_faces[face_index]);
            }
            result.copy_vertex_indices = identity_indices(result.vertices.size());
            result.index_map = identity_indices(result.vertices.size());
            result.topology_changed = true;
            return result;
        }
    }

    const std::set<int> selected_faces = selected_faces_from_topology_json(item, faces, vertices.size());
    if (selected_faces.empty()) {
        return result;
    }
    result.vertices = vertices;
    result.faces.reserve(faces.size());
    result.source_face_indices.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        result.faces.push_back(faces[face_index]);
        result.source_face_indices.push_back(source_faces[face_index]);
    }
    if (result.removed_faces <= 0) {
        result.vertices.clear();
        result.faces.clear();
        result.source_face_indices.clear();
        return result;
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.index_map = identity_indices(result.vertices.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_extrude_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "extrude";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }
    const Vec3 offset = vec3_or(edit.get("offset"), vec3_or(edit.get("delta"), {0.0, 0.0, 0.25}));

    auto next_source_face_index = [&source_faces]() {
        int next = static_cast<int>(source_faces.size());
        for (const int source_face_index : source_faces) {
            next = std::max(next, source_face_index + 1);
        }
        return next;
    };

    result.copy_vertex_indices.reserve(result.vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < result.vertices.size(); ++vertex_index) {
        result.copy_vertex_indices.push_back(static_cast<int>(vertex_index));
    }

    std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    if (!selected_faces.empty()) {
        std::map<int, int> extruded_vertices;
        std::map<std::array<int, 2>, int> edge_counts;
        std::map<std::array<int, 2>, std::array<int, 2>> edge_order;
        std::vector<std::array<int, 2>> edge_order_keys;
        std::vector<std::array<int, 3>> selected_face_values;
        std::vector<int> selected_source_faces;
        for (const int face_index : selected_faces) {
            if (face_index < 0 || static_cast<std::size_t>(face_index) >= original_faces.size()) {
                continue;
            }
            const std::array<int, 3>& face = original_faces[static_cast<std::size_t>(face_index)];
            selected_face_values.push_back(face);
            selected_source_faces.push_back(source_faces[static_cast<std::size_t>(face_index)]);
            for (const int vertex_index : face) {
                if (extruded_vertices.find(vertex_index) != extruded_vertices.end()) {
                    continue;
                }
                const int new_index = static_cast<int>(result.vertices.size());
                result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(vertex_index)], offset));
                result.copy_vertex_indices.push_back(vertex_index);
                result.changed_vertices.push_back(new_index);
                extruded_vertices[vertex_index] = new_index;
                ++result.added_vertices;
            }
            const std::array<int, 2> oriented_edges[3] = {
                std::array<int, 2>{face[0], face[1]},
                std::array<int, 2>{face[1], face[2]},
                std::array<int, 2>{face[2], face[0]},
            };
            for (const auto& oriented : oriented_edges) {
                const std::array<int, 2> key = edge_key(oriented[0], oriented[1]);
                if (edge_counts.find(key) == edge_counts.end()) {
                    edge_order_keys.push_back(key);
                    edge_order[key] = oriented;
                }
                ++edge_counts[key];
            }
        }
        if (extruded_vertices.empty() || selected_face_values.empty()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }

        result.faces = original_faces;
        result.source_face_indices = source_faces;
        for (std::size_t selected_index = 0; selected_index < selected_face_values.size(); ++selected_index) {
            const auto& face = selected_face_values[selected_index];
            result.faces.push_back({
                extruded_vertices[face[0]],
                extruded_vertices[face[1]],
                extruded_vertices[face[2]],
            });
            result.source_face_indices.push_back(
                selected_index < selected_source_faces.size()
                    ? selected_source_faces[selected_index]
                    : static_cast<int>(selected_index)
            );
            ++result.added_faces;
        }
        int next_generated_source_face = next_source_face_index();
        for (const auto& edge : edge_order_keys) {
            if (edge_counts[edge] != 1) {
                continue;
            }
            const std::array<int, 2>& oriented = edge_order[edge];
            const int a = oriented[0];
            const int b = oriented[1];
            const int na = extruded_vertices[a];
            const int nb = extruded_vertices[b];
            result.faces.push_back({a, b, nb});
            result.source_face_indices.push_back(next_generated_source_face++);
            result.faces.push_back({a, nb, na});
            result.source_face_indices.push_back(next_generated_source_face++);
            result.added_faces += 2;
        }
        result.topology_changed = result.added_vertices > 0 && result.added_faces > 0;
        if (!result.topology_changed) {
            result.vertices.clear();
            result.faces.clear();
            result.copy_vertex_indices.clear();
            result.source_face_indices.clear();
            result.changed_vertices.clear();
        }
        return result;
    }

    std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    if (!original_faces.empty() && !selected_edges.empty()) {
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(original_faces);
        std::set<std::array<int, 2>> kept_edges;
        for (const auto& edge : selected_edges) {
            if (existing_edges.find(edge) != existing_edges.end()) {
                kept_edges.insert(edge);
            }
        }
        selected_edges = std::move(kept_edges);
    }
    if (selected_edges.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        return result;
    }

    std::map<int, int> extruded_vertices;
    result.faces = original_faces;
    result.source_face_indices = source_faces;
    int next_generated_source_face = next_source_face_index();
    for (const auto& edge : selected_edges) {
        const int a = edge[0];
        const int b = edge[1];
        if (extruded_vertices.find(a) == extruded_vertices.end()) {
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(a)], offset));
            result.copy_vertex_indices.push_back(a);
            result.changed_vertices.push_back(new_index);
            extruded_vertices[a] = new_index;
            ++result.added_vertices;
        }
        if (extruded_vertices.find(b) == extruded_vertices.end()) {
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(add_vec3(result.vertices[static_cast<std::size_t>(b)], offset));
            result.copy_vertex_indices.push_back(b);
            result.changed_vertices.push_back(new_index);
            extruded_vertices[b] = new_index;
            ++result.added_vertices;
        }
        const int na = extruded_vertices[a];
        const int nb = extruded_vertices[b];
        result.faces.push_back({a, b, nb});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.faces.push_back({a, nb, na});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.added_faces += 2;
    }
    result.topology_changed = result.added_vertices > 0 && result.added_faces > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

SubmeshMeshEditResult run_inset_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "inset";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    double amount = number_or(edit.get("amount"), 0.25);
    amount = std::max(0.0, std::min(0.95, amount));
    if (amount <= 1.0e-8) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }

    const std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    if (selected_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<std::array<int, 3>> selected_face_values;
    std::vector<int> selected_source_faces;
    std::set<int> selected_vertices;
    selected_face_values.reserve(selected_faces.size());
    selected_source_faces.reserve(selected_faces.size());
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= original_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = original_faces[static_cast<std::size_t>(face_index)];
        selected_face_values.push_back(face);
        selected_source_faces.push_back(source_faces[static_cast<std::size_t>(face_index)]);
        selected_vertices.insert(face[0]);
        selected_vertices.insert(face[1]);
        selected_vertices.insert(face[2]);
    }
    if (selected_face_values.empty() || selected_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    Vec3 center{0.0, 0.0, 0.0};
    for (const int vertex_index : selected_vertices) {
        center = add_vec3(center, result.vertices[static_cast<std::size_t>(vertex_index)]);
    }
    center = scale_vec3(center, 1.0 / static_cast<double>(selected_vertices.size()));

    result.copy_vertex_indices.reserve(result.vertices.size() + selected_vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < result.vertices.size(); ++vertex_index) {
        result.copy_vertex_indices.push_back(static_cast<int>(vertex_index));
    }

    std::map<int, int> inner_vertices;
    std::map<std::array<int, 2>, int> edge_counts;
    std::map<std::array<int, 2>, std::array<int, 2>> edge_order;
    std::vector<std::array<int, 2>> edge_order_keys;
    for (const auto& face : selected_face_values) {
        for (const int vertex_index : face) {
            if (inner_vertices.find(vertex_index) != inner_vertices.end()) {
                continue;
            }
            const Vec3 vertex = result.vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 inset_vertex{
                vertex[0] + (center[0] - vertex[0]) * amount,
                vertex[1] + (center[1] - vertex[1]) * amount,
                vertex[2] + (center[2] - vertex[2]) * amount,
            };
            const int new_index = static_cast<int>(result.vertices.size());
            result.vertices.push_back(inset_vertex);
            result.copy_vertex_indices.push_back(vertex_index);
            result.changed_vertices.push_back(new_index);
            inner_vertices[vertex_index] = new_index;
            ++result.added_vertices;
        }
        const std::array<int, 2> oriented_edges[3] = {
            std::array<int, 2>{face[0], face[1]},
            std::array<int, 2>{face[1], face[2]},
            std::array<int, 2>{face[2], face[0]},
        };
        for (const auto& oriented : oriented_edges) {
            const std::array<int, 2> key = edge_key(oriented[0], oriented[1]);
            if (edge_counts.find(key) == edge_counts.end()) {
                edge_order_keys.push_back(key);
                edge_order[key] = oriented;
            }
            ++edge_counts[key];
        }
    }
    if (inner_vertices.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.changed_vertices.clear();
        return result;
    }

    result.faces.reserve(original_faces.size() + selected_face_values.size() + edge_order_keys.size() * 2);
    result.source_face_indices.reserve(original_faces.size() + selected_face_values.size() + edge_order_keys.size() * 2);
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        result.faces.push_back(original_faces[face_index]);
        result.source_face_indices.push_back(source_faces[face_index]);
    }
    for (std::size_t selected_index = 0; selected_index < selected_face_values.size(); ++selected_index) {
        const auto& face = selected_face_values[selected_index];
        result.faces.push_back({
            inner_vertices[face[0]],
            inner_vertices[face[1]],
            inner_vertices[face[2]],
        });
        result.source_face_indices.push_back(
            selected_index < selected_source_faces.size()
                ? selected_source_faces[selected_index]
                : static_cast<int>(selected_index)
        );
        ++result.added_faces;
    }

    int next_generated_source_face = static_cast<int>(source_faces.size());
    for (const int source_face_index : source_faces) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    for (const auto& edge : edge_order_keys) {
        if (edge_counts[edge] != 1) {
            continue;
        }
        const std::array<int, 2>& oriented = edge_order[edge];
        const int a = oriented[0];
        const int b = oriented[1];
        const int ia = inner_vertices[a];
        const int ib = inner_vertices[b];
        result.faces.push_back({a, b, ib});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.faces.push_back({a, ib, ia});
        result.source_face_indices.push_back(next_generated_source_face++);
        result.added_faces += 2;
    }
    result.topology_changed = result.added_vertices > 0 && result.added_faces > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

SubmeshMeshEditResult run_compact_orphans_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "compact_orphans";
    result.index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const JsonValue* raw_faces = item.get("faces");
    const JsonValue* raw_faces_binary = item.get("faces_binary");
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    const std::size_t raw_face_count = raw_faces_binary != nullptr
        ? faces.size()
        : raw_faces != nullptr && raw_faces->type == JsonValue::Type::Array
        ? raw_faces->array_value.size()
        : 0;
    if (result.index < 0 || vertices.empty()) {
        return result;
    }

    std::set<int> used_vertices;
    for (const auto& face : faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    const bool removed_invalid_faces = faces.size() != raw_face_count;
    if (used_vertices.size() == vertices.size() && !removed_invalid_faces) {
        return result;
    }

    std::map<int, int> index_map;
    for (const int old_index : used_vertices) {
        index_map[old_index] = static_cast<int>(result.vertices.size());
        result.vertices.push_back(vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const auto& face = faces[face_index];
        const auto a = index_map.find(face[0]);
        const auto b = index_map.find(face[1]);
        const auto c = index_map.find(face[2]);
        if (a != index_map.end() && b != index_map.end() && c != index_map.end()) {
            result.faces.push_back({a->second, b->second, c->second});
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    }
    result.index_map.assign(vertices.size(), -1);
    for (const auto& item_map : index_map) {
        result.index_map[static_cast<std::size_t>(item_map.first)] = item_map.second;
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());
    result.removed_faces = static_cast<int>(raw_face_count) - static_cast<int>(faces.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_split_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "split";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());

    std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    if (selected_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::set<int> selected_face_vertices;
    std::set<int> unselected_face_vertices;
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const auto& face = original_faces[face_index];
        std::set<int>& target = selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()
            ? selected_face_vertices
            : unselected_face_vertices;
        target.insert(face[0]);
        target.insert(face[1]);
        target.insert(face[2]);
    }

    std::vector<int> shared_vertices;
    std::set_intersection(
        selected_face_vertices.begin(),
        selected_face_vertices.end(),
        unselected_face_vertices.begin(),
        unselected_face_vertices.end(),
        std::back_inserter(shared_vertices)
    );
    if (shared_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    result.copy_vertex_indices.reserve(result.vertices.size() + shared_vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    std::map<int, int> split_map;
    for (const int vertex_index : shared_vertices) {
        const int new_index = static_cast<int>(result.vertices.size());
        result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
        result.copy_vertex_indices.push_back(vertex_index);
        result.changed_vertices.push_back(new_index);
        split_map[vertex_index] = new_index;
        ++result.added_vertices;
    }

    result.faces.reserve(original_faces.size());
    result.source_face_indices.reserve(original_faces.size());
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        std::array<int, 3> face = original_faces[face_index];
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            for (int& vertex_index : face) {
                const auto found = split_map.find(vertex_index);
                if (found != split_map.end()) {
                    vertex_index = found->second;
                }
            }
        }
        result.faces.push_back(face);
        result.source_face_indices.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_edge_split_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "edge_split";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    result.copy_vertex_indices.reserve(result.vertices.size() + original_faces.size() * 3u);
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    result.faces.reserve(original_faces.size());
    result.source_face_indices.reserve(original_faces.size());
    if (!selected_edges.empty()) {
        std::set<std::array<int, 2>> seen_edges;
        for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
            const std::array<int, 3>& original_face = original_faces[face_index];
            std::array<int, 3> face = original_face;
            std::map<int, int> replacements;
            const std::array<int, 2> edges[3] = {
                edge_key(original_face[0], original_face[1]),
                edge_key(original_face[1], original_face[2]),
                edge_key(original_face[2], original_face[0]),
            };
            for (const auto& edge : edges) {
                if (selected_edges.find(edge) == selected_edges.end()) {
                    continue;
                }
                if (seen_edges.find(edge) == seen_edges.end()) {
                    seen_edges.insert(edge);
                    continue;
                }
                for (const int vertex_index : edge) {
                    if (replacements.find(vertex_index) != replacements.end()) {
                        continue;
                    }
                    const int new_index = static_cast<int>(result.vertices.size());
                    result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                    result.copy_vertex_indices.push_back(vertex_index);
                    result.changed_vertices.push_back(new_index);
                    replacements[vertex_index] = new_index;
                    ++result.added_vertices;
                }
            }
            if (!replacements.empty()) {
                for (int& vertex_index : face) {
                    const auto found = replacements.find(vertex_index);
                    if (found != replacements.end()) {
                        vertex_index = found->second;
                    }
                }
            }
            result.faces.push_back(face);
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    } else {
        const std::set<int> selected_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
        if (selected_faces.empty()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
            std::array<int, 3> face = original_faces[face_index];
            if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
                for (int& vertex_index : face) {
                    const int new_index = static_cast<int>(result.vertices.size());
                    result.vertices.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                    result.copy_vertex_indices.push_back(vertex_index);
                    result.changed_vertices.push_back(new_index);
                    vertex_index = new_index;
                    ++result.added_vertices;
                }
            }
            result.faces.push_back(face);
            result.source_face_indices.push_back(
                face_index < source_faces.size()
                    ? source_faces[face_index]
                    : static_cast<int>(face_index)
            );
        }
    }
    result.topology_changed = result.added_vertices > 0;
    if (!result.topology_changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.changed_vertices.clear();
    }
    return result;
}

int loop_cut_count_from_edit(const JsonValue& edit) {
    const int value = int_or(edit.get("cuts"), int_or(edit.get("count"), int_or(edit.get("segments"), 1)));
    return std::max(1, std::min(16, value));
}

double loop_cut_factor_from_edit(const JsonValue* value) {
    const double parsed = number_or(value, 0.5);
    if (!std::isfinite(parsed)) {
        return 0.5;
    }
    return std::max(1.0e-6, std::min(1.0 - 1.0e-6, parsed));
}

std::vector<double> loop_cut_fractions_from_edit(const JsonValue& edit, int cut_count) {
    cut_count = std::max(1, std::min(16, cut_count));
    if (cut_count == 1 && (edit.get("factor") != nullptr || edit.get("position") != nullptr)) {
        return {loop_cut_factor_from_edit(edit.get("factor") != nullptr ? edit.get("factor") : edit.get("position"))};
    }
    std::vector<double> fractions;
    fractions.reserve(static_cast<std::size_t>(cut_count));
    for (int cut_index = 1; cut_index <= cut_count; ++cut_index) {
        fractions.push_back(static_cast<double>(cut_index) / static_cast<double>(cut_count + 1));
    }
    return fractions;
}

int append_loop_cut_vertex(SubmeshMeshEditResult& result, int left, int right, double fraction, std::set<int>& changed) {
    if (left < 0
        || right < 0
        || left == right
        || static_cast<std::size_t>(left) >= result.vertices.size()
        || static_cast<std::size_t>(right) >= result.vertices.size()) {
        return -1;
    }
    fraction = std::max(0.0, std::min(1.0, fraction));
    const Vec3 left_vertex = result.vertices[static_cast<std::size_t>(left)];
    const Vec3 right_vertex = result.vertices[static_cast<std::size_t>(right)];
    const int new_index = static_cast<int>(result.vertices.size());
    result.vertices.push_back({
        left_vertex[0] + (right_vertex[0] - left_vertex[0]) * fraction,
        left_vertex[1] + (right_vertex[1] - left_vertex[1]) * fraction,
        left_vertex[2] + (right_vertex[2] - left_vertex[2]) * fraction,
    });
    result.copy_vertex_indices.push_back(-1);
    result.vertex_blends.push_back({new_index, left, right, fraction});
    changed.insert(new_index);
    ++result.added_vertices;
    return new_index;
}

void append_loop_edge_cut_faces(
    std::vector<std::array<int, 3>>& out_faces,
    std::vector<int>& out_source_faces,
    const std::vector<int>& edge_vertices,
    int opposite_vertex,
    int source_face_index
) {
    if (edge_vertices.size() < 2) {
        return;
    }
    for (std::size_t index = 0; index + 1 < edge_vertices.size(); ++index) {
        out_faces.push_back({edge_vertices[index], edge_vertices[index + 1], opposite_vertex});
        out_source_faces.push_back(source_face_index);
    }
}

SubmeshMeshEditResult run_loop_cut_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "loop_cut";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    if (selected_edges.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    if (source_faces.size() != original_faces.size()) {
        source_faces = identity_indices(original_faces.size());
    }
    result.copy_vertex_indices.reserve(result.vertices.size() + selected_edges.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }

    const int cut_count = loop_cut_count_from_edit(edit);
    const std::vector<double> cut_fractions = loop_cut_fractions_from_edit(edit, cut_count);
    std::map<std::array<int, 2>, std::vector<int>> edge_cut_vertices;
    std::map<std::array<int, 2>, int> edge_midpoints;
    std::set<int> changed;

    auto cut_vertices = [&](int a, int b) -> std::vector<int> {
        const std::array<int, 2> key = edge_key(a, b);
        auto found = edge_cut_vertices.find(key);
        if (found == edge_cut_vertices.end()) {
            std::vector<int> vertices;
            vertices.reserve(cut_fractions.size());
            for (const double fraction : cut_fractions) {
                const int new_index = append_loop_cut_vertex(result, key[0], key[1], fraction, changed);
                if (new_index < 0) {
                    return std::vector<int>{};
                }
                vertices.push_back(new_index);
            }
            found = edge_cut_vertices.emplace(key, std::move(vertices)).first;
        }
        std::vector<int> vertices = found->second;
        if (key[0] != a || key[1] != b) {
            std::reverse(vertices.begin(), vertices.end());
        }
        return vertices;
    };

    auto cut_point = [&](int a, int b) -> int {
        const std::array<int, 2> key = edge_key(a, b);
        const auto found = edge_midpoints.find(key);
        if (found != edge_midpoints.end()) {
            return found->second;
        }
        const double fraction = cut_fractions.empty() ? 0.5 : cut_fractions[0];
        const int new_index = append_loop_cut_vertex(result, key[0], key[1], fraction, changed);
        if (new_index >= 0) {
            edge_midpoints[key] = new_index;
        }
        return new_index;
    };

    result.faces.reserve(original_faces.size() + selected_edges.size() * static_cast<std::size_t>(std::max(1, cut_count)));
    result.source_face_indices.reserve(result.faces.capacity());
    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const std::array<int, 3>& face = original_faces[face_index];
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const int source_face_index = source_faces[face_index];
        const std::array<int, 2> ab_key = edge_key(a, b);
        const std::array<int, 2> bc_key = edge_key(b, c);
        const std::array<int, 2> ca_key = edge_key(c, a);
        const bool has_ab = selected_edges.find(ab_key) != selected_edges.end();
        const bool has_bc = selected_edges.find(bc_key) != selected_edges.end();
        const bool has_ca = selected_edges.find(ca_key) != selected_edges.end();
        const int matched_count = (has_ab ? 1 : 0) + (has_bc ? 1 : 0) + (has_ca ? 1 : 0);
        if (matched_count <= 0) {
            result.faces.push_back(face);
            result.source_face_indices.push_back(source_face_index);
        } else if (matched_count == 1) {
            if (has_ab) {
                std::vector<int> edge_vertices{a};
                std::vector<int> cuts = cut_vertices(a, b);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(b);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, c, source_face_index);
            } else if (has_bc) {
                std::vector<int> edge_vertices{b};
                std::vector<int> cuts = cut_vertices(b, c);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(c);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, a, source_face_index);
            } else {
                std::vector<int> edge_vertices{c};
                std::vector<int> cuts = cut_vertices(c, a);
                edge_vertices.insert(edge_vertices.end(), cuts.begin(), cuts.end());
                edge_vertices.push_back(a);
                append_loop_edge_cut_faces(result.faces, result.source_face_indices, edge_vertices, b, source_face_index);
            }
        } else if (matched_count == 2) {
            if (has_ab && has_bc) {
                const int ab = cut_point(a, b);
                const int bc = cut_point(b, c);
                result.faces.push_back({ab, b, bc});
                result.faces.push_back({a, ab, bc});
                result.faces.push_back({a, bc, c});
            } else if (has_bc && has_ca) {
                const int bc = cut_point(b, c);
                const int ca = cut_point(c, a);
                result.faces.push_back({bc, c, ca});
                result.faces.push_back({a, b, bc});
                result.faces.push_back({a, bc, ca});
            } else {
                const int ca = cut_point(c, a);
                const int ab = cut_point(a, b);
                result.faces.push_back({ca, a, ab});
                result.faces.push_back({ab, b, c});
                result.faces.push_back({ab, c, ca});
            }
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
        } else {
            const int ab = cut_point(a, b);
            const int bc = cut_point(b, c);
            const int ca = cut_point(c, a);
            result.faces.push_back({a, ab, ca});
            result.faces.push_back({ab, b, bc});
            result.faces.push_back({ca, bc, c});
            result.faces.push_back({ab, bc, ca});
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
            result.source_face_indices.push_back(source_face_index);
        }
    }

    if (changed.empty()) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.vertex_blends.clear();
        return result;
    }
    result.changed_vertices.assign(changed.begin(), changed.end());
    result.added_faces = std::max(0, static_cast<int>(result.faces.size()) - static_cast<int>(original_faces.size()));
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult compact_remapped_edit_result(
    const std::string& action,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<int>& source_faces,
    const std::map<int, int>& remap,
    const std::map<int, Vec3>& moved_vertices
) {
    SubmeshMeshEditResult result;
    result.action = action;
    result.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return result;
    }

    std::set<std::array<int, 3>> seen_faces;
    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    kept_faces.reserve(faces.size());
    kept_source_faces.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        std::array<int, 3> remapped{
            remap.count(face[0]) ? remap.at(face[0]) : face[0],
            remap.count(face[1]) ? remap.at(face[1]) : face[1],
            remap.count(face[2]) ? remap.at(face[2]) : face[2],
        };
        if (remapped[0] == remapped[1] || remapped[1] == remapped[2] || remapped[0] == remapped[2]) {
            ++result.removed_faces;
            continue;
        }
        if (seen_faces.find(remapped) != seen_faces.end()) {
            ++result.removed_faces;
            continue;
        }
        seen_faces.insert(remapped);
        kept_faces.push_back(remapped);
        kept_source_faces.push_back(
            face_index < source_faces.size()
                ? source_faces[face_index]
                : static_cast<int>(face_index)
        );
    }

    std::set<int> used_vertices;
    for (const std::array<int, 3>& face : kept_faces) {
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    std::map<int, int> compacted_by_old;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        compacted_by_old[old_index] = static_cast<int>(result.vertices.size());
        const auto moved = moved_vertices.find(old_index);
        result.vertices.push_back(moved != moved_vertices.end() ? moved->second : vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = compacted_by_old.find(face[0]);
        const auto b = compacted_by_old.find(face[1]);
        const auto c = compacted_by_old.find(face[2]);
        if (a == compacted_by_old.end() || b == compacted_by_old.end() || c == compacted_by_old.end()) {
            result.vertices.clear();
            result.faces.clear();
            result.copy_vertex_indices.clear();
            result.source_face_indices.clear();
            return result;
        }
        result.faces.push_back({a->second, b->second, c->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }

    result.index_map.assign(vertices.size(), -1);
    for (std::size_t old_index = 0; old_index < vertices.size(); ++old_index) {
        const int remapped_old = remap.count(static_cast<int>(old_index))
            ? remap.at(static_cast<int>(old_index))
            : static_cast<int>(old_index);
        if (remapped_old != static_cast<int>(old_index)) {
            continue;
        }
        const auto found = compacted_by_old.find(static_cast<int>(old_index));
        if (found != compacted_by_old.end()) {
            result.index_map[old_index] = found->second;
        }
    }
    result.removed_vertices = static_cast<int>(vertices.size()) - static_cast<int>(result.vertices.size());

    bool moved = false;
    for (const auto& item_moved : moved_vertices) {
        if (item_moved.first >= 0
            && static_cast<std::size_t>(item_moved.first) < vertices.size()
            && !same_vec3(vertices[static_cast<std::size_t>(item_moved.first)], item_moved.second)) {
            moved = true;
            break;
        }
    }
    const bool changed = !remap.empty() || moved || result.removed_vertices > 0 || result.removed_faces > 0;
    if (!changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        result.index_map.clear();
        return result;
    }
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_merge_edit_for_submesh(const JsonValue& item) {
    const int submesh_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }
    SubmeshMeshEditResult empty;
    empty.action = "merge";
    empty.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return empty;
    }

    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    if (selected.size() < 2) {
        return empty;
    }
    const int keeper = *selected.begin();
    const Vec3 center = average_vertices(vertices, std::vector<int>(selected.begin(), selected.end()));
    std::map<int, int> remap;
    for (const int vertex_index : selected) {
        if (vertex_index != keeper) {
            remap[vertex_index] = keeper;
        }
    }
    std::map<int, Vec3> moved_vertices;
    moved_vertices[keeper] = center;
    return compact_remapped_edit_result("merge", submesh_index, vertices, faces, source_faces, remap, moved_vertices);
}

SubmeshMeshEditResult run_weld_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    const int submesh_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
    if (source_faces.size() != faces.size()) {
        source_faces = identity_indices(faces.size());
    }
    SubmeshMeshEditResult empty;
    empty.action = "weld";
    empty.index = submesh_index;
    if (submesh_index < 0 || vertices.empty() || faces.empty()) {
        return empty;
    }

    const std::set<int> selected = selected_vertices_from_edit_domains(item, vertices.size(), faces);
    if (selected.size() < 2) {
        return empty;
    }
    double threshold = number_or(edit.get("threshold"), number_or(edit.get("distance"), number_or(edit.get("merge_distance"), 1e-5)));
    if (!std::isfinite(threshold) || threshold <= 0.0) {
        threshold = 1e-5;
    }
    const double threshold_squared = threshold * threshold;

    std::map<int, int> remap;
    std::map<int, Vec3> moved_vertices;
    const std::vector<int> sorted_indices(selected.begin(), selected.end());
    for (std::size_t position = 0; position < sorted_indices.size(); ++position) {
        const int keeper = sorted_indices[position];
        if (remap.find(keeper) != remap.end()) {
            continue;
        }
        std::vector<int> cluster{keeper};
        const Vec3& keeper_vertex = vertices[static_cast<std::size_t>(keeper)];
        for (std::size_t candidate_offset = position + 1; candidate_offset < sorted_indices.size(); ++candidate_offset) {
            const int candidate = sorted_indices[candidate_offset];
            if (remap.find(candidate) != remap.end()) {
                continue;
            }
            if (distance_squared_vec3(keeper_vertex, vertices[static_cast<std::size_t>(candidate)]) <= threshold_squared) {
                cluster.push_back(candidate);
            }
        }
        if (cluster.size() < 2) {
            continue;
        }
        moved_vertices[keeper] = average_vertices(vertices, cluster);
        for (std::size_t cluster_index = 1; cluster_index < cluster.size(); ++cluster_index) {
            remap[cluster[cluster_index]] = keeper;
        }
    }
    if (remap.empty()) {
        return empty;
    }
    return compact_remapped_edit_result("weld", submesh_index, vertices, faces, source_faces, remap, moved_vertices);
}

SubmeshMeshEditResult run_duplicate_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "duplicate";
    result.index = int_or(item.get("index"), -1);
    result.source_index = result.index;
    result.name_suffix = " duplicate";
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (result.index < 0 || source_vertices.empty() || source_faces.empty()) {
        return result;
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return result;
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::set<int> used_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = source_faces[static_cast<std::size_t>(face_index)];
        kept_faces.push_back(face);
        kept_source_faces.push_back(
            static_cast<std::size_t>(face_index) < source_face_indices.size()
                ? source_face_indices[static_cast<std::size_t>(face_index)]
                : face_index
        );
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    if (kept_faces.empty() || used_vertices.empty()) {
        return result;
    }

    std::map<int, int> remap;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        const int new_index = static_cast<int>(result.vertices.size());
        remap[old_index] = new_index;
        result.vertices.push_back(source_vertices[static_cast<std::size_t>(old_index)]);
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = remap.find(face[0]);
        const auto b = remap.find(face[1]);
        const auto c = remap.find(face[2]);
        if (a == remap.end() || b == remap.end() || c == remap.end()) {
            continue;
        }
        result.faces.push_back({a->second, b->second, c->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }
    if (result.faces.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }

    result.append_submesh = true;
    result.added_vertices = static_cast<int>(result.vertices.size());
    result.added_faces = static_cast<int>(result.faces.size());
    result.topology_changed = true;
    return result;
}

int mirror_axis_index_from_edit(const JsonValue& edit) {
    std::string axis = string_or(edit.get("axis"), "x");
    std::transform(axis.begin(), axis.end(), axis.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (axis == "y" || axis == "1") {
        return 1;
    }
    if (axis == "z" || axis == "2") {
        return 2;
    }
    return 0;
}

Vec3 mirrored_vec3_axis(Vec3 value, int axis_index) {
    if (axis_index < 0 || axis_index > 2) {
        axis_index = 0;
    }
    value[static_cast<std::size_t>(axis_index)] = -value[static_cast<std::size_t>(axis_index)];
    return value;
}

SubmeshMeshEditResult run_mirror_edit_for_submesh(const JsonValue& item, const JsonValue& edit) {
    SubmeshMeshEditResult result;
    result.action = "mirror";
    result.index = int_or(item.get("index"), -1);
    result.source_index = result.index;
    result.name_suffix = " mirror";
    result.mirror_axis_index = mirror_axis_index_from_edit(edit);
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (result.index < 0 || source_vertices.empty() || source_faces.empty()) {
        return result;
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return result;
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::set<int> used_vertices;
    for (const int face_index : selected_faces) {
        if (face_index < 0 || static_cast<std::size_t>(face_index) >= source_faces.size()) {
            continue;
        }
        const std::array<int, 3>& face = source_faces[static_cast<std::size_t>(face_index)];
        kept_faces.push_back(face);
        kept_source_faces.push_back(
            static_cast<std::size_t>(face_index) < source_face_indices.size()
                ? source_face_indices[static_cast<std::size_t>(face_index)]
                : face_index
        );
        used_vertices.insert(face[0]);
        used_vertices.insert(face[1]);
        used_vertices.insert(face[2]);
    }
    if (kept_faces.empty() || used_vertices.empty()) {
        return result;
    }

    std::map<int, int> remap;
    result.vertices.reserve(used_vertices.size());
    result.copy_vertex_indices.reserve(used_vertices.size());
    for (const int old_index : used_vertices) {
        if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
            result.vertices.clear();
            result.copy_vertex_indices.clear();
            return result;
        }
        const int new_index = static_cast<int>(result.vertices.size());
        remap[old_index] = new_index;
        result.vertices.push_back(mirrored_vec3_axis(source_vertices[static_cast<std::size_t>(old_index)], result.mirror_axis_index));
        result.copy_vertex_indices.push_back(old_index);
    }

    result.faces.reserve(kept_faces.size());
    result.source_face_indices.reserve(kept_faces.size());
    for (std::size_t face_index = 0; face_index < kept_faces.size(); ++face_index) {
        const std::array<int, 3>& face = kept_faces[face_index];
        const auto a = remap.find(face[0]);
        const auto b = remap.find(face[1]);
        const auto c = remap.find(face[2]);
        if (a == remap.end() || b == remap.end() || c == remap.end()) {
            continue;
        }
        result.faces.push_back({a->second, c->second, b->second});
        result.source_face_indices.push_back(kept_source_faces[face_index]);
    }
    if (result.faces.empty()) {
        result.vertices.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }

    result.append_submesh = true;
    result.added_vertices = static_cast<int>(result.vertices.size());
    result.added_faces = static_cast<int>(result.faces.size());
    result.topology_changed = true;
    return result;
}

std::vector<SubmeshMeshEditResult> run_separate_edit_for_submesh(const JsonValue& item) {
    const int source_index = int_or(item.get("index"), -1);
    const std::vector<Vec3> source_vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> source_faces = mesh_faces_from_item(item, source_vertices.size());
    if (source_index < 0 || source_vertices.empty() || source_faces.empty()) {
        return {};
    }
    const std::vector<int> source_face_indices = mesh_source_face_indices_from_item(item, source_faces.size());
    const std::set<int> selected_faces = selected_faces_from_topology_json(item, source_faces, source_vertices.size());
    if (selected_faces.empty()) {
        return {};
    }

    std::vector<std::array<int, 3>> kept_faces;
    std::vector<int> kept_source_faces;
    std::vector<std::array<int, 3>> moved_faces;
    std::vector<int> moved_source_faces;
    for (std::size_t face_index = 0; face_index < source_faces.size(); ++face_index) {
        const int source_face = face_index < source_face_indices.size()
            ? source_face_indices[face_index]
            : static_cast<int>(face_index);
        if (selected_faces.find(static_cast<int>(face_index)) != selected_faces.end()) {
            moved_faces.push_back(source_faces[face_index]);
            moved_source_faces.push_back(source_face);
        } else {
            kept_faces.push_back(source_faces[face_index]);
            kept_source_faces.push_back(source_face);
        }
    }
    if (moved_faces.empty()) {
        return {};
    }

    auto compact_faces = [&](const std::vector<std::array<int, 3>>& faces) {
        SubmeshMeshEditResult result;
        std::set<int> used_vertices;
        for (const auto& face : faces) {
            used_vertices.insert(face[0]);
            used_vertices.insert(face[1]);
            used_vertices.insert(face[2]);
        }
        std::map<int, int> remap;
        result.vertices.reserve(used_vertices.size());
        result.copy_vertex_indices.reserve(used_vertices.size());
        for (const int old_index : used_vertices) {
            if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
                result.vertices.clear();
                result.copy_vertex_indices.clear();
                result.faces.clear();
                return result;
            }
            const int new_index = static_cast<int>(result.vertices.size());
            remap[old_index] = new_index;
            result.vertices.push_back(source_vertices[static_cast<std::size_t>(old_index)]);
            result.copy_vertex_indices.push_back(old_index);
        }
        result.faces.reserve(faces.size());
        for (const auto& face : faces) {
            const auto a = remap.find(face[0]);
            const auto b = remap.find(face[1]);
            const auto c = remap.find(face[2]);
            if (a == remap.end() || b == remap.end() || c == remap.end()) {
                result.vertices.clear();
                result.copy_vertex_indices.clear();
                result.faces.clear();
                return result;
            }
            result.faces.push_back({a->second, b->second, c->second});
        }
        return result;
    };

    SubmeshMeshEditResult source_result = compact_faces(kept_faces);
    if (!kept_faces.empty() && source_result.faces.empty()) {
        return {};
    }
    source_result.action = "separate";
    source_result.index = source_index;
    source_result.source_face_indices = kept_source_faces;
    source_result.removed_faces = static_cast<int>(moved_faces.size());
    source_result.removed_vertices = static_cast<int>(source_vertices.size()) - static_cast<int>(source_result.vertices.size());
    source_result.topology_changed = true;

    SubmeshMeshEditResult append_result = compact_faces(moved_faces);
    if (append_result.faces.empty()) {
        return {};
    }
    append_result.action = "separate";
    append_result.index = source_index;
    append_result.append_submesh = true;
    append_result.source_index = source_index;
    append_result.name_suffix = " split";
    append_result.source_face_indices = moved_source_faces;
    append_result.added_vertices = static_cast<int>(append_result.vertices.size());
    append_result.added_faces = static_cast<int>(append_result.faces.size());
    append_result.topology_changed = true;

    return {std::move(source_result), std::move(append_result)};
}

SubmeshMeshEditResult run_fix_winding_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fix_winding";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    const std::vector<Vec3> normals = mesh_normals_from_item(item);
    if (result.index < 0 || result.vertices.empty() || original_faces.empty() || normals.size() != result.vertices.size()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    result.faces = original_faces;
    result.source_face_indices = source_faces.size() == original_faces.size()
        ? source_faces
        : identity_indices(original_faces.size());
    result.copy_vertex_indices.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        result.copy_vertex_indices.push_back(static_cast<int>(index));
    }
    bool changed = false;
    for (std::array<int, 3>& face : result.faces) {
        const Vec3 face_normal = normalized_vec3(
            face_cross(
                result.vertices[static_cast<std::size_t>(face[0])],
                result.vertices[static_cast<std::size_t>(face[1])],
                result.vertices[static_cast<std::size_t>(face[2])]
            ),
            {0.0, 0.0, 0.0}
        );
        const Vec3 average_normal = normalized_vec3(
            add_vec3(
                add_vec3(normals[static_cast<std::size_t>(face[0])], normals[static_cast<std::size_t>(face[1])]),
                normals[static_cast<std::size_t>(face[2])]
            ),
            {0.0, 0.0, 0.0}
        );
        if (dot_vec3(face_normal, average_normal) < -1.0e-8) {
            std::swap(face[1], face[2]);
            changed = true;
        }
    }
    if (!changed) {
        result.vertices.clear();
        result.faces.clear();
        result.copy_vertex_indices.clear();
        result.source_face_indices.clear();
        return result;
    }
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_fill_holes_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fill_holes";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::map<std::array<int, 2>, int> edge_use_count;
    for (const auto& face : original_faces) {
        ++edge_use_count[edge_key(face[0], face[1])];
        ++edge_use_count[edge_key(face[1], face[2])];
        ++edge_use_count[edge_key(face[2], face[0])];
    }
    std::set<std::array<int, 2>> pending_edges;
    for (const auto& item_count : edge_use_count) {
        if (item_count.second == 1) {
            pending_edges.insert(item_count.first);
        }
    }
    if (pending_edges.empty()) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::set<std::array<int, 3>> existing_faces;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
    }

    std::vector<std::array<int, 3>> added_faces;
    while (!pending_edges.empty()) {
        std::set<std::array<int, 2>> component;
        std::set<int> component_vertices;
        const std::array<int, 2> seed = *pending_edges.begin();
        pending_edges.erase(pending_edges.begin());
        component.insert(seed);
        component_vertices.insert(seed[0]);
        component_vertices.insert(seed[1]);
        bool changed = true;
        while (changed) {
            changed = false;
            for (auto edge_it = pending_edges.begin(); edge_it != pending_edges.end();) {
                const std::array<int, 2> edge = *edge_it;
                if (component_vertices.find(edge[0]) != component_vertices.end()
                    || component_vertices.find(edge[1]) != component_vertices.end()) {
                    component.insert(edge);
                    component_vertices.insert(edge[0]);
                    component_vertices.insert(edge[1]);
                    edge_it = pending_edges.erase(edge_it);
                    changed = true;
                } else {
                    ++edge_it;
                }
            }
        }

        const std::vector<int> order = closed_edge_loop_order(component);
        if (order.size() == 3) {
            const std::array<int, 3> face{order[0], order[1], order[2]};
            const std::array<int, 3> key = sorted_face_key(face);
            if (existing_faces.find(key) == existing_faces.end()) {
                added_faces.push_back(face);
                existing_faces.insert(key);
            }
        } else if (order.size() == 4) {
            const std::array<int, 3> first{order[0], order[1], order[2]};
            const std::array<int, 3> second{order[0], order[2], order[3]};
            for (const auto& face : {first, second}) {
                const std::array<int, 3> key = sorted_face_key(face);
                if (existing_faces.find(key) == existing_faces.end()) {
                    added_faces.push_back(face);
                    existing_faces.insert(key);
                }
            }
        }
    }
    if (added_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.insert(result.faces.end(), added_faces.begin(), added_faces.end());
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    for (std::size_t added_index = 0; added_index < added_faces.size(); ++added_index) {
        result.source_face_indices.push_back(next_generated_source_face + static_cast<int>(added_index));
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = static_cast<int>(added_faces.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_fill_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "fill";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::set<int> selected_vertices = selected_vertices_from_binary_or_json(item, result.vertices.size());
    const std::set<std::array<int, 2>> selected_edges = selected_edges_from_binary_or_json(item, result.vertices.size());
    std::vector<int> edge_loop;
    if (!selected_edges.empty()) {
        for (const auto& edge : selected_edges) {
            selected_vertices.insert(edge[0]);
            selected_vertices.insert(edge[1]);
        }
        edge_loop = closed_edge_loop_order(selected_edges);
    }
    if (selected_vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<int> indices;
    bool use_edge_loop = !edge_loop.empty() && edge_loop.size() == selected_vertices.size();
    if (use_edge_loop) {
        for (const int index : edge_loop) {
            if (selected_vertices.find(index) == selected_vertices.end()) {
                use_edge_loop = false;
                break;
            }
        }
    }
    if (use_edge_loop) {
        indices = std::move(edge_loop);
    } else {
        indices.assign(selected_vertices.begin(), selected_vertices.end());
    }
    if (indices.size() != 3 && indices.size() != 4) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::set<std::array<int, 3>> existing_faces;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
    }

    std::vector<std::array<int, 3>> faces_to_add;
    const std::set<int> selected_set(indices.begin(), indices.end());
    if (indices.size() == 3) {
        const std::array<int, 3> face{indices[0], indices[1], indices[2]};
        if (existing_faces.find(sorted_face_key(face)) == existing_faces.end()) {
            faces_to_add.push_back(face);
        }
    } else {
        int inside_count = 0;
        std::set<int> covered_vertices;
        for (const auto& face : existing_faces) {
            if (selected_set.find(face[0]) == selected_set.end()
                || selected_set.find(face[1]) == selected_set.end()
                || selected_set.find(face[2]) == selected_set.end()) {
                continue;
            }
            ++inside_count;
            covered_vertices.insert(face[0]);
            covered_vertices.insert(face[1]);
            covered_vertices.insert(face[2]);
        }
        if (inside_count >= 2 && covered_vertices == selected_set) {
            result.vertices.clear();
            return result;
        }
        const std::array<int, 3> first{indices[0], indices[1], indices[2]};
        const std::array<int, 3> second{indices[0], indices[2], indices[3]};
        for (const auto& face : {first, second}) {
            if (existing_faces.find(sorted_face_key(face)) == existing_faces.end()) {
                faces_to_add.push_back(face);
            }
        }
    }
    if (faces_to_add.empty()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.insert(result.faces.end(), faces_to_add.begin(), faces_to_add.end());
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    for (std::size_t added_index = 0; added_index < faces_to_add.size(); ++added_index) {
        result.source_face_indices.push_back(next_generated_source_face + static_cast<int>(added_index));
    }
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = static_cast<int>(faces_to_add.size());
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_triangulate_display_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "triangulate_display";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<DisplayFace> display_faces = display_faces_from_json(item.get("display_faces"), result.vertices.size());
    if (display_faces.empty() && item.get("display_faces") == nullptr) {
        const std::vector<std::array<int, 3>> current_faces = mesh_faces_from_item(item, result.vertices.size());
        display_faces.reserve(current_faces.size());
        for (std::size_t face_index = 0; face_index < current_faces.size(); ++face_index) {
            const auto& current = current_faces[face_index];
            DisplayFace face;
            face.indices = {current[0], current[1], current[2]};
            face.source_index = static_cast<int>(face_index);
            face.valid = true;
            display_faces.push_back(std::move(face));
        }
    }
    if (display_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    std::vector<std::array<int, 3>> triangulated_faces;
    std::vector<int> triangulated_source_faces;
    for (const DisplayFace& face : display_faces) {
        if (!face.valid || face.indices.size() < 3) {
            continue;
        }
        if (face.indices.size() == 3) {
            const std::array<int, 3> triangle{face.indices[0], face.indices[1], face.indices[2]};
            if (triangle[0] != triangle[1] && triangle[0] != triangle[2] && triangle[1] != triangle[2]) {
                triangulated_faces.push_back(triangle);
                triangulated_source_faces.push_back(face.source_index);
            }
            continue;
        }
        for (std::size_t offset = 1; offset + 1 < face.indices.size(); ++offset) {
            const std::array<int, 3> triangle{
                face.indices[0],
                face.indices[offset],
                face.indices[offset + 1],
            };
            if (triangle[0] != triangle[1] && triangle[0] != triangle[2] && triangle[1] != triangle[2]) {
                triangulated_faces.push_back(triangle);
                triangulated_source_faces.push_back(face.source_index);
            }
        }
    }

    bool unchanged = display_faces.size() == triangulated_faces.size();
    if (unchanged) {
        for (std::size_t face_index = 0; face_index < display_faces.size(); ++face_index) {
            const DisplayFace& face = display_faces[face_index];
            const std::array<int, 3>& triangle = triangulated_faces[face_index];
            if (!face.valid
                || face.indices.size() != 3
                || face.indices[0] != triangle[0]
                || face.indices[1] != triangle[1]
                || face.indices[2] != triangle[2]) {
                unchanged = false;
                break;
            }
        }
    }
    if (unchanged) {
        result.vertices.clear();
        return result;
    }

    result.faces = std::move(triangulated_faces);
    result.source_face_indices = std::move(triangulated_source_faces);
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.removed_faces = std::max(0, static_cast<int>(display_faces.size()) - static_cast<int>(result.faces.size()));
    result.added_faces = std::max(0, static_cast<int>(result.faces.size()) - static_cast<int>(display_faces.size()));
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_bridge_edit_for_submesh(const JsonValue& item) {
    SubmeshMeshEditResult result;
    result.action = "bridge";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::set<std::array<int, 2>> selected_edge_set = selected_edges_from_binary_or_json(item, result.vertices.size());
    if (selected_edge_set.size() != 2) {
        result.vertices.clear();
        return result;
    }
    const std::vector<std::array<int, 2>> selected_edges(selected_edge_set.begin(), selected_edge_set.end());
    const int a = selected_edges[0][0];
    const int b = selected_edges[0][1];
    const int c = selected_edges[1][0];
    const int d = selected_edges[1][1];
    const std::set<int> selected_vertices{a, b, c, d};
    if (selected_vertices.size() != 4) {
        result.vertices.clear();
        return result;
    }

    auto sorted_face_key = [](std::array<int, 3> face) {
        std::sort(face.begin(), face.end());
        return face;
    };
    std::map<std::array<int, 2>, int> edge_use_count;
    std::set<std::array<int, 3>> existing_faces;
    bool existing_inside_selected_vertices = false;
    for (const auto& face : original_faces) {
        existing_faces.insert(sorted_face_key(face));
        ++edge_use_count[edge_key(face[0], face[1])];
        ++edge_use_count[edge_key(face[1], face[2])];
        ++edge_use_count[edge_key(face[2], face[0])];
        if (selected_vertices.find(face[0]) != selected_vertices.end()
            && selected_vertices.find(face[1]) != selected_vertices.end()
            && selected_vertices.find(face[2]) != selected_vertices.end()) {
            existing_inside_selected_vertices = true;
        }
    }
    if (edge_use_count[edge_key(a, b)] > 1 || edge_use_count[edge_key(c, d)] > 1 || existing_inside_selected_vertices) {
        result.vertices.clear();
        return result;
    }

    const std::array<int, 3> first{a, b, d};
    const std::array<int, 3> second{a, d, c};
    if (existing_faces.find(sorted_face_key(first)) != existing_faces.end()
        || existing_faces.find(sorted_face_key(second)) != existing_faces.end()) {
        result.vertices.clear();
        return result;
    }

    result.faces = original_faces;
    result.faces.push_back(first);
    result.faces.push_back(second);
    result.source_face_indices = mesh_source_face_indices_from_item(item, original_faces.size());
    if (result.source_face_indices.size() != original_faces.size()) {
        result.source_face_indices = identity_indices(original_faces.size());
    }
    int next_generated_source_face = static_cast<int>(result.source_face_indices.size());
    for (const int source_face_index : result.source_face_indices) {
        next_generated_source_face = std::max(next_generated_source_face, source_face_index + 1);
    }
    result.source_face_indices.push_back(next_generated_source_face);
    result.source_face_indices.push_back(next_generated_source_face + 1);
    result.copy_vertex_indices = identity_indices(result.vertices.size());
    result.added_faces = 2;
    result.topology_changed = true;
    return result;
}

SubmeshMeshEditResult run_subdivide_edit_for_submesh(const JsonValue& item, const JsonValue& edit, bool refine) {
    SubmeshMeshEditResult result;
    result.action = refine ? "refine_smooth" : "subdivide";
    result.index = int_or(item.get("index"), -1);
    result.vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> original_faces = mesh_faces_from_item(item, result.vertices.size());
    if (result.index < 0 || result.vertices.empty() || original_faces.empty()) {
        result.vertices.clear();
        return result;
    }
    const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, original_faces.size());
    std::set<int> split_faces = selected_faces_from_topology_json(item, original_faces, result.vertices.size());
    const int face_limit = std::max(1, int_or(edit.get("max_faces_per_submesh"), 256));
    while (static_cast<int>(split_faces.size()) > face_limit) {
        auto last = split_faces.end();
        --last;
        split_faces.erase(last);
    }
    if (split_faces.empty()) {
        result.vertices.clear();
        return result;
    }

    const int old_vertex_count = static_cast<int>(result.vertices.size());
    result.copy_vertex_indices.reserve(result.vertices.size());
    for (int index = 0; index < old_vertex_count; ++index) {
        result.copy_vertex_indices.push_back(index);
    }
    std::map<std::array<int, 2>, int> edge_midpoints;
    std::set<int> changed;
    auto midpoint_index = [&](int a, int b) -> int {
        const std::array<int, 2> key = edge_key(a, b);
        const auto found = edge_midpoints.find(key);
        if (found != edge_midpoints.end()) {
            return found->second;
        }
        const Vec3 midpoint = scale_vec3(add_vec3(result.vertices[static_cast<std::size_t>(a)], result.vertices[static_cast<std::size_t>(b)]), 0.5);
        const int new_index = static_cast<int>(result.vertices.size());
        result.vertices.push_back(midpoint);
        result.copy_vertex_indices.push_back(-1);
        result.vertex_blends.push_back({new_index, a, b, 0.5});
        edge_midpoints[key] = new_index;
        changed.insert(new_index);
        ++result.added_vertices;
        return new_index;
    };

    for (std::size_t face_index = 0; face_index < original_faces.size(); ++face_index) {
        const auto& face = original_faces[face_index];
        const int source_face_index = face_index < source_faces.size()
            ? source_faces[face_index]
            : static_cast<int>(face_index);
        if (split_faces.find(static_cast<int>(face_index)) == split_faces.end()) {
            result.faces.push_back(face);
            result.source_face_indices.push_back(source_face_index);
            continue;
        }
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const int ab = midpoint_index(a, b);
        const int bc = midpoint_index(b, c);
        const int ca = midpoint_index(c, a);
        changed.insert(a);
        changed.insert(b);
        changed.insert(c);
        changed.insert(ab);
        changed.insert(bc);
        changed.insert(ca);
        result.faces.push_back({a, ab, ca});
        result.faces.push_back({ab, b, bc});
        result.faces.push_back({ca, bc, c});
        result.faces.push_back({ab, bc, ca});
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.source_face_indices.push_back(source_face_index);
        result.added_faces += 3;
    }

    if (refine && !changed.empty()) {
        const double strength = std::max(0.0, std::min(1.0, number_or(edit.get("smooth_strength"), number_or(edit.get("strength"), 0.5))));
        const int iterations = std::max(1, std::min(12, int_or(edit.get("smooth_iterations"), int_or(edit.get("iterations"), 2))));
        std::vector<Vec3> relax = result.vertices;
        const std::vector<std::set<int>> adjacency = build_vertex_adjacency(result.vertices.size(), result.faces);
        for (int iteration = 0; iteration < iterations; ++iteration) {
            std::vector<Vec3> next = relax;
            for (const int index : changed) {
                if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) {
                    continue;
                }
                const std::set<int>& neighbors = adjacency[static_cast<std::size_t>(index)];
                if (neighbors.empty()) {
                    continue;
                }
                Vec3 sum{0.0, 0.0, 0.0};
                int count = 0;
                for (const int neighbor : neighbors) {
                    if (neighbor < 0 || static_cast<std::size_t>(neighbor) >= relax.size()) {
                        continue;
                    }
                    sum = add_vec3(sum, relax[static_cast<std::size_t>(neighbor)]);
                    ++count;
                }
                if (count <= 0) {
                    continue;
                }
                const Vec3 avg = scale_vec3(sum, 1.0 / static_cast<double>(count));
                const Vec3 vertex = relax[static_cast<std::size_t>(index)];
                next[static_cast<std::size_t>(index)] = add_vec3(vertex, scale_vec3(sub_vec3(avg, vertex), strength));
            }
            relax = std::move(next);
        }
        result.vertices = std::move(relax);
    }

    result.changed_vertices.assign(changed.begin(), changed.end());
    result.topology_changed = true;
    return result;
}

std::vector<Vec2> preview_uvs_for_result(const JsonValue& item, const SubmeshMeshEditResult& result) {
    if (result.vertices.empty()) {
        return {};
    }
    const std::vector<Vec2> input_uvs = mesh_uvs_from_item(item);
    if (input_uvs.empty()) {
        return std::vector<Vec2>(result.vertices.size(), {0.0, 0.0});
    }
    if (!result.topology_changed && input_uvs.size() == result.vertices.size()) {
        return input_uvs;
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<Vec2> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input_uvs.size()) {
            output.push_back(input_uvs[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend != blends.end()
            && blend->second.left >= 0
            && blend->second.right >= 0
            && static_cast<std::size_t>(blend->second.left) < input_uvs.size()
            && static_cast<std::size_t>(blend->second.right) < input_uvs.size()) {
            const Vec2 left = input_uvs[static_cast<std::size_t>(blend->second.left)];
            const Vec2 right = input_uvs[static_cast<std::size_t>(blend->second.right)];
            const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
            output.push_back({
                left[0] + (right[0] - left[0]) * factor,
                left[1] + (right[1] - left[1]) * factor,
            });
            continue;
        }
        output.push_back({0.0, 0.0});
    }
    return output;
}

std::vector<Vec3> vec3_values_for_result(const std::vector<Vec3>& input, const SubmeshMeshEditResult& result) {
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<Vec3> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()
            || blend->second.left < 0
            || blend->second.right < 0
            || static_cast<std::size_t>(blend->second.left) >= input.size()
            || static_cast<std::size_t>(blend->second.right) >= input.size()) {
            return {};
        }
        const Vec3 left = input[static_cast<std::size_t>(blend->second.left)];
        const Vec3 right = input[static_cast<std::size_t>(blend->second.right)];
        const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
        output.push_back({
            left[0] + (right[0] - left[0]) * factor,
            left[1] + (right[1] - left[1]) * factor,
            left[2] + (right[2] - left[2]) * factor,
        });
    }
    return output;
}

std::vector<double> double_values_for_result(const std::vector<double>& input, const SubmeshMeshEditResult& result) {
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<double> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()
            || blend->second.left < 0
            || blend->second.right < 0
            || static_cast<std::size_t>(blend->second.left) >= input.size()
            || static_cast<std::size_t>(blend->second.right) >= input.size()) {
            return {};
        }
        const double left = input[static_cast<std::size_t>(blend->second.left)];
        const double right = input[static_cast<std::size_t>(blend->second.right)];
        const double factor = std::max(0.0, std::min(1.0, blend->second.factor));
        output.push_back(left + (right - left) * factor);
    }
    return output;
}

bool valid_bone_assignments(const BoneAssignments& bones) {
    return !bones.indices.empty() && bones.indices.size() == bones.weights.size();
}

bool blended_bone_assignment(
    const BoneAssignments& input,
    int left,
    int right,
    double factor,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    if (!valid_bone_assignments(input)
        || left < 0
        || right < 0
        || static_cast<std::size_t>(left) >= input.indices.size()
        || static_cast<std::size_t>(right) >= input.indices.size()
        || input.indices[static_cast<std::size_t>(left)].size() != input.weights[static_cast<std::size_t>(left)].size()
        || input.indices[static_cast<std::size_t>(right)].size() != input.weights[static_cast<std::size_t>(right)].size()) {
        return false;
    }
    factor = std::max(0.0, std::min(1.0, factor));
    std::map<int, double> weights_by_bone;
    const std::vector<int>& left_indices = input.indices[static_cast<std::size_t>(left)];
    const std::vector<double>& left_weights = input.weights[static_cast<std::size_t>(left)];
    for (std::size_t index = 0; index < left_indices.size(); ++index) {
        const int bone = left_indices[index];
        const double weight = left_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            weights_by_bone[bone] += weight * (1.0 - factor);
        }
    }
    const std::vector<int>& right_indices = input.indices[static_cast<std::size_t>(right)];
    const std::vector<double>& right_weights = input.weights[static_cast<std::size_t>(right)];
    for (std::size_t index = 0; index < right_indices.size(); ++index) {
        const int bone = right_indices[index];
        const double weight = right_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            weights_by_bone[bone] += weight * factor;
        }
    }
    if (weights_by_bone.empty()) {
        out_indices.clear();
        out_weights.clear();
        return true;
    }
    std::vector<std::pair<int, double>> strongest(weights_by_bone.begin(), weights_by_bone.end());
    std::sort(strongest.begin(), strongest.end(), [](const auto& left_item, const auto& right_item) {
        if (left_item.second != right_item.second) {
            return left_item.second > right_item.second;
        }
        return left_item.first < right_item.first;
    });
    if (strongest.size() > 4) {
        strongest.resize(4);
    }
    double total = 0.0;
    for (const auto& item : strongest) {
        total += item.second;
    }
    if (total <= 0.0 || !std::isfinite(total)) {
        out_indices.clear();
        out_weights.clear();
        return true;
    }
    out_indices.clear();
    out_weights.clear();
    out_indices.reserve(strongest.size());
    out_weights.reserve(strongest.size());
    for (const auto& item : strongest) {
        out_indices.push_back(item.first);
        out_weights.push_back(item.second / total);
    }
    return true;
}

BoneAssignments bone_values_for_result(const BoneAssignments& input, const SubmeshMeshEditResult& result) {
    if (!valid_bone_assignments(input)) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    BoneAssignments output;
    output.indices.reserve(result.vertices.size());
    output.weights.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.indices.size()) {
            if (input.indices[static_cast<std::size_t>(source_index)].size() != input.weights[static_cast<std::size_t>(source_index)].size()) {
                return {};
            }
            output.indices.push_back(input.indices[static_cast<std::size_t>(source_index)]);
            output.weights.push_back(input.weights[static_cast<std::size_t>(source_index)]);
            continue;
        }
        const auto blend = blends.find(static_cast<int>(index));
        if (blend == blends.end()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        if (!blended_bone_assignment(input, blend->second.left, blend->second.right, blend->second.factor, indices, weights)) {
            return {};
        }
        output.indices.push_back(std::move(indices));
        output.weights.push_back(std::move(weights));
    }
    return output;
}

std::vector<int> bone_assignment_counts(const BoneAssignments& bones) {
    std::vector<int> counts;
    if (!valid_bone_assignments(bones)) {
        return counts;
    }
    counts.reserve(bones.indices.size());
    for (std::size_t index = 0; index < bones.indices.size(); ++index) {
        if (bones.indices[index].size() != bones.weights[index].size() || bones.indices[index].size() > static_cast<std::size_t>(INT_MAX)) {
            return {};
        }
        counts.push_back(static_cast<int>(bones.indices[index].size()));
    }
    return counts;
}

std::vector<int> flatten_bone_indices(const BoneAssignments& bones) {
    std::vector<int> flat;
    if (!valid_bone_assignments(bones)) {
        return flat;
    }
    for (const std::vector<int>& vertex_indices : bones.indices) {
        flat.insert(flat.end(), vertex_indices.begin(), vertex_indices.end());
    }
    return flat;
}

std::vector<double> flatten_bone_weights(const BoneAssignments& bones) {
    std::vector<double> flat;
    if (!valid_bone_assignments(bones)) {
        return flat;
    }
    for (const std::vector<double>& vertex_weights : bones.weights) {
        flat.insert(flat.end(), vertex_weights.begin(), vertex_weights.end());
    }
    return flat;
}

std::vector<std::pair<int, double>> clean_weight_pairs_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights
) {
    std::map<int, double> merged;
    const std::size_t count = std::min(raw_indices.size(), raw_weights.size());
    for (std::size_t index = 0; index < count; ++index) {
        const int bone = raw_indices[index];
        const double weight = raw_weights[index];
        if (bone >= 0 && weight > 0.0 && std::isfinite(weight)) {
            merged[bone] += weight;
        }
    }
    return std::vector<std::pair<int, double>>(merged.begin(), merged.end());
}

void pack_weight_pairs_native(
    std::vector<std::pair<int, double>> pairs,
    int preferred_bone,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> positive;
    positive.reserve(pairs.size());
    for (const auto& item : pairs) {
        if (item.first >= 0 && item.second > 0.0 && std::isfinite(item.second)) {
            positive.push_back(item);
        }
    }
    if (positive.empty()) {
        out_indices.clear();
        out_weights.clear();
        return;
    }
    if (positive.size() > 4) {
        std::vector<std::pair<int, double>> selected;
        for (const auto& item : positive) {
            if (item.first == preferred_bone) {
                selected.push_back(item);
                break;
            }
        }
        std::vector<std::pair<int, double>> others;
        for (const auto& item : positive) {
            if (item.first != preferred_bone) {
                others.push_back(item);
            }
        }
        std::sort(others.begin(), others.end(), [](const auto& left, const auto& right) {
            if (left.second != right.second) {
                return left.second > right.second;
            }
            return left.first < right.first;
        });
        for (const auto& item : others) {
            if (selected.size() >= 4) {
                break;
            }
            selected.push_back(item);
        }
        positive = std::move(selected);
    }
    double total = 0.0;
    for (const auto& item : positive) {
        total += item.second;
    }
    if (total <= 0.0 || !std::isfinite(total)) {
        out_indices.clear();
        out_weights.clear();
        return;
    }
    std::sort(positive.begin(), positive.end(), [](const auto& left, const auto& right) {
        return left.first < right.first;
    });
    out_indices.clear();
    out_weights.clear();
    out_indices.reserve(positive.size());
    out_weights.reserve(positive.size());
    for (const auto& item : positive) {
        out_indices.push_back(item.first);
        out_weights.push_back(item.second / total);
    }
}

void normalize_weight_row_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    pack_weight_pairs_native(clean_weight_pairs_native(raw_indices, raw_weights), -1, out_indices, out_weights);
}

void nudge_bone_weight_native(
    const std::vector<int>& raw_indices,
    const std::vector<double>& raw_weights,
    int bone_index,
    double delta,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> pairs = clean_weight_pairs_native(raw_indices, raw_weights);
    double current = 0.0;
    std::vector<std::pair<int, double>> others;
    for (const auto& item : pairs) {
        if (item.first == bone_index) {
            current += item.second;
        } else {
            others.push_back(item);
        }
    }
    const double target = std::max(0.0, std::min(1.0, current + delta));
    if (target > 0.0) {
        double other_total = 0.0;
        for (const auto& item : others) {
            other_total += item.second;
        }
        if (other_total > 0.0 && std::isfinite(other_total)) {
            const double scale = (1.0 - target) / other_total;
            for (auto& item : others) {
                item.second *= scale;
            }
            others.push_back({bone_index, target});
            pairs = std::move(others);
        } else {
            pairs = {{bone_index, 1.0}};
        }
    } else {
        pairs = std::move(others);
    }
    pack_weight_pairs_native(std::move(pairs), bone_index, out_indices, out_weights);
}

std::vector<int> optional_source_vertex_map_from_item(const JsonValue& item, std::size_t vertex_count) {
    if (item.get("source_vertex_map_binary") != nullptr
        || item.get("source_vertex_map") != nullptr
        || item.get("source_vertex_map_start") != nullptr) {
        const std::vector<int> values = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (values.size() == vertex_count) {
            return values;
        }
    }
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (session->source_vertex_map.size() == vertex_count) {
            return session->source_vertex_map;
        }
    }
    return {};
}

BoneAssignments source_bone_assignments_from_item(const JsonValue& item) {
    BoneAssignments result;
    if (item.get("source_bone_counts_binary") == nullptr
        || item.get("source_bone_indices_binary") == nullptr
        || item.get("source_bone_weights_binary") == nullptr) {
        return result;
    }
    const std::vector<int> counts = int_vector_from_binary_or_json(item, "source_bone_counts_binary", "source_bone_counts");
    const std::vector<int> flat_indices = int_vector_from_binary_or_json(item, "source_bone_indices_binary", "source_bone_indices_flat");
    const std::vector<double> flat_weights = double_vector_from_binary_or_json(item, "source_bone_weights_binary", "source_bone_weights_flat");
    if (flat_indices.size() != flat_weights.size()) {
        return {};
    }
    std::size_t flat_offset = 0;
    result.indices.reserve(counts.size());
    result.weights.reserve(counts.size());
    for (const int raw_count : counts) {
        if (raw_count < 0) {
            return {};
        }
        const std::size_t count = static_cast<std::size_t>(raw_count);
        if (flat_offset + count > flat_indices.size()) {
            return {};
        }
        std::vector<int> indices;
        std::vector<double> weights;
        indices.reserve(count);
        weights.reserve(count);
        for (std::size_t index = 0; index < count; ++index) {
            const int bone = flat_indices[flat_offset + index];
            const double weight = flat_weights[flat_offset + index];
            if (bone < 0 || !std::isfinite(weight)) {
                return {};
            }
            indices.push_back(bone);
            weights.push_back(weight);
        }
        result.indices.push_back(std::move(indices));
        result.weights.push_back(std::move(weights));
        flat_offset += count;
    }
    if (flat_offset != flat_indices.size()) {
        return {};
    }
    return result;
}

std::map<int, int> bone_remap_from_item(const JsonValue& item) {
    const std::vector<int> source = int_vector_from_binary_or_json(item, "bone_remap_source_binary", "bone_remap_source");
    const std::vector<int> target = int_vector_from_binary_or_json(item, "bone_remap_target_binary", "bone_remap_target");
    std::map<int, int> remap;
    const std::size_t count = std::min(source.size(), target.size());
    for (std::size_t index = 0; index < count; ++index) {
        if (source[index] >= 0 && target[index] >= 0) {
            remap[source[index]] = target[index];
        }
    }
    return remap;
}

int nearest_source_vertex_index_native(const Vec3& target, const std::vector<Vec3>& source_vertices) {
    int best_index = -1;
    double best_distance = std::numeric_limits<double>::infinity();
    for (std::size_t index = 0; index < source_vertices.size(); ++index) {
        const double distance = distance_squared_vec3(target, source_vertices[index]);
        if (distance < best_distance) {
            best_distance = distance;
            best_index = static_cast<int>(index);
        }
    }
    return best_index;
}

std::string suffixed_output_path(const std::string& path, const std::string& suffix) {
    return path.empty() ? path : path + suffix;
}

void transfer_weight_row_native(
    const std::vector<int>& source_indices,
    const std::vector<double>& source_weights,
    bool remap_enabled,
    const std::map<int, int>& bone_remap,
    std::vector<int>& out_indices,
    std::vector<double>& out_weights
) {
    std::vector<std::pair<int, double>> pairs = clean_weight_pairs_native(source_indices, source_weights);
    if (remap_enabled) {
        std::vector<std::pair<int, double>> remapped;
        remapped.reserve(pairs.size());
        for (const auto& item : pairs) {
            const auto found = bone_remap.find(item.first);
            if (found != bone_remap.end()) {
                remapped.push_back({found->second, item.second});
            }
        }
        pairs = std::move(remapped);
    }
    pack_weight_pairs_native(std::move(pairs), -1, out_indices, out_weights);
}

std::vector<int> source_vertex_values_for_result(
    const JsonValue& item,
    const SubmeshMeshEditResult& result,
    const std::string& binary_key,
    const std::string& json_key,
    int default_value
) {
    std::vector<int> input = binary_key == "source_vertex_offsets_binary"
        ? source_vertex_offsets_from_item(item)
        : binary_key == "source_vertex_map_binary"
        ? int_vector_from_binary_or_json(
            item,
            binary_key,
            json_key,
            "source_vertex_map_start",
            "source_vertex_map_count"
        )
        : int_vector_from_binary_or_json(item, binary_key, json_key);
    if (input.empty()) {
        if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
            if (binary_key == "source_vertex_map_binary") {
                input = session->source_vertex_map;
            } else if (binary_key == "source_vertex_offsets_binary") {
                input = session->source_vertex_offsets;
            }
        }
    }
    if (input.empty()) {
        return {};
    }
    std::map<int, VertexBlend> blends;
    for (const VertexBlend& blend : result.vertex_blends) {
        blends[blend.index] = blend;
    }
    std::vector<int> output;
    output.reserve(result.vertices.size());
    for (std::size_t index = 0; index < result.vertices.size(); ++index) {
        const int source_index = index < result.copy_vertex_indices.size() ? result.copy_vertex_indices[index] : static_cast<int>(index);
        if (source_index >= 0 && static_cast<std::size_t>(source_index) < input.size()) {
            output.push_back(input[static_cast<std::size_t>(source_index)]);
            continue;
        }
        if (blends.find(static_cast<int>(index)) != blends.end()) {
            output.push_back(default_value);
            continue;
        }
        return {};
    }
    return output;
}

std::vector<SubmeshMeshEditResult> run_mesh_edit(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string sparse_snapshot_id = sparse_snapshot_id_from_root(root);
    const JsonValue* edit = root.get("edit");
    if (edit == nullptr || edit->type != JsonValue::Type::Object) {
        throw std::runtime_error("missing edit object");
    }
    std::string operation = string_or(edit->get("operation"), string_or(root.get("operation"), ""));
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    std::vector<SubmeshMeshEditResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        std::vector<SubmeshMeshEditResult> item_results;
        if (operation == "brush") {
            item_results.push_back(run_brush_edit_for_submesh(item, *edit));
        } else if (operation == "delete") {
            item_results.push_back(run_delete_edit_for_submesh(item, *edit));
        } else if (operation == "dissolve") {
            item_results.push_back(run_dissolve_edit_for_submesh(item));
        } else if (operation == "extrude") {
            item_results.push_back(run_extrude_edit_for_submesh(item, *edit));
        } else if (operation == "inset") {
            item_results.push_back(run_inset_edit_for_submesh(item, *edit));
        } else if (operation == "compact_orphans") {
            item_results.push_back(run_compact_orphans_for_submesh(item));
        } else if (operation == "split") {
            item_results.push_back(run_split_edit_for_submesh(item));
        } else if (operation == "duplicate") {
            item_results.push_back(run_duplicate_edit_for_submesh(item));
        } else if (operation == "mirror") {
            item_results.push_back(run_mirror_edit_for_submesh(item, *edit));
        } else if (operation == "separate") {
            item_results = run_separate_edit_for_submesh(item);
        } else if (operation == "fix_winding") {
            item_results.push_back(run_fix_winding_edit_for_submesh(item));
        } else if (operation == "fill_holes") {
            item_results.push_back(run_fill_holes_edit_for_submesh(item));
        } else if (operation == "fill") {
            item_results.push_back(run_fill_edit_for_submesh(item));
        } else if (operation == "loop_cut") {
            item_results.push_back(run_loop_cut_edit_for_submesh(item, *edit));
        } else if (operation == "edge_split") {
            item_results.push_back(run_edge_split_edit_for_submesh(item));
        } else if (operation == "merge") {
            item_results.push_back(run_merge_edit_for_submesh(item));
        } else if (operation == "weld") {
            item_results.push_back(run_weld_edit_for_submesh(item, *edit));
        } else if (operation == "triangulate_display") {
            item_results.push_back(run_triangulate_display_edit_for_submesh(item));
        } else if (operation == "bridge") {
            item_results.push_back(run_bridge_edit_for_submesh(item));
        } else if (operation == "subdivide") {
            item_results.push_back(run_subdivide_edit_for_submesh(item, *edit, false));
        } else if (operation == "refine_smooth") {
            item_results.push_back(run_subdivide_edit_for_submesh(item, *edit, true));
        } else {
            throw std::runtime_error("unsupported mesh edit operation: " + operation);
        }
        for (SubmeshMeshEditResult& result : item_results) {
            result.changed_positions_path = string_or(item.get("changed_positions_output_path"), "");
            result.before_positions_path = string_or(item.get("before_positions_output_path"), "");
            result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
            result.vertices_path = string_or(item.get("vertices_output_path"), "");
            result.faces_path = string_or(item.get("faces_output_path"), "");
            result.normals_path = string_or(item.get("normals_output_path"), "");
            result.uvs_path = string_or(item.get("uvs_output_path"), "");
            result.tangents_path = string_or(item.get("tangents_output_path"), "");
            result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
            result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
            result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
            result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
            result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
            result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
            result.preview_triangle_path = string_or(item.get("preview_triangle_output_path"), "");
            result.copy_vertex_indices_path = string_or(item.get("copy_vertex_indices_output_path"), "");
            result.vertex_blend_indices_path = string_or(item.get("vertex_blend_indices_output_path"), "");
            result.vertex_blend_factors_path = string_or(item.get("vertex_blend_factors_output_path"), "");
            result.index_map_path = string_or(item.get("index_map_output_path"), "");
            result.suppress_vertex_remap_report = bool_or(
                item.get("suppress_vertex_remap_report"),
                bool_or(edit->get("suppress_vertex_remap_report"), false)
            );
            if (result.append_submesh) {
                const std::string source_name = string_or(item.get("name"), "");
                const std::string base_name = source_name.empty()
                    ? std::string("part_") + std::to_string(result.source_index >= 0 ? result.source_index : result.index)
                    : source_name;
                if (result.name.empty()) {
                    result.name = base_name + result.name_suffix;
                }
                if (result.material.empty()) {
                    result.material = string_or(item.get("material"), "");
                }
                if (result.texture.empty()) {
                    result.texture = string_or(item.get("texture"), "");
                }
                if (result.extra_attrs.type != JsonValue::Type::Object) {
                    if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
                        if (extra_attrs->type == JsonValue::Type::Object) {
                            result.extra_attrs = *extra_attrs;
                        }
                    }
                }
                const std::string suffix = ".append";
                result.changed_positions_path = suffixed_output_path(result.changed_positions_path, suffix);
                result.before_positions_path = suffixed_output_path(result.before_positions_path, suffix);
                result.changed_vertices_path = suffixed_output_path(result.changed_vertices_path, suffix);
                result.vertices_path = suffixed_output_path(result.vertices_path, suffix);
                result.faces_path = suffixed_output_path(result.faces_path, suffix);
                result.normals_path = suffixed_output_path(result.normals_path, suffix);
                result.uvs_path = suffixed_output_path(result.uvs_path, suffix);
                result.tangents_path = suffixed_output_path(result.tangents_path, suffix);
                result.tangent_signs_path = suffixed_output_path(result.tangent_signs_path, suffix);
                result.bone_counts_path = suffixed_output_path(result.bone_counts_path, suffix);
                result.bone_indices_path = suffixed_output_path(result.bone_indices_path, suffix);
                result.bone_weights_path = suffixed_output_path(result.bone_weights_path, suffix);
                result.source_vertex_map_path = suffixed_output_path(result.source_vertex_map_path, suffix);
                result.source_vertex_offsets_path = suffixed_output_path(result.source_vertex_offsets_path, suffix);
                result.preview_triangle_path = suffixed_output_path(result.preview_triangle_path, suffix);
                result.copy_vertex_indices_path = suffixed_output_path(result.copy_vertex_indices_path, suffix);
                result.vertex_blend_indices_path = suffixed_output_path(result.vertex_blend_indices_path, suffix);
                result.vertex_blend_factors_path = suffixed_output_path(result.vertex_blend_factors_path, suffix);
                result.index_map_path = suffixed_output_path(result.index_map_path, suffix);
            }
            if (result.index >= 0 && (result.topology_changed || !result.vertices.empty() || !result.faces.empty() || !result.changed_vertices.empty())) {
                if (result.topology_changed) {
                    if (!result.normals_path.empty()) {
                        result.normals = vec3_values_for_result(mesh_normals_from_item(item), result);
                    }
                    result.preview_uvs = preview_uvs_for_result(item, result);
                    result.tangents = vec3_values_for_result(mesh_tangents_from_item(item), result);
                    result.tangent_signs = double_values_for_result(mesh_tangent_signs_from_item(item), result);
                    if (result.mirror_axis_index >= 0) {
                        for (Vec3& normal : result.normals) {
                            normal = mirrored_vec3_axis(normal, result.mirror_axis_index);
                        }
                        for (Vec3& tangent : result.tangents) {
                            tangent = mirrored_vec3_axis(tangent, result.mirror_axis_index);
                        }
                    }
                    result.bones = bone_values_for_result(mesh_bones_from_item(item), result);
                    result.source_vertex_map = source_vertex_values_for_result(
                        item,
                        result,
                        "source_vertex_map_binary",
                        "source_vertex_map",
                        -1
                    );
                    result.source_vertex_offsets = source_vertex_values_for_result(
                        item,
                        result,
                        "source_vertex_offsets_binary",
                        "source_vertex_offsets",
                        -1
                    );
                    if (result.source_face_indices.size() != result.faces.size()) {
                        result.source_face_indices = identity_indices(result.faces.size());
                    }
                } else if (!result.changed_vertices.empty()) {
                    result.preview_uvs = preview_uvs_for_result(item, result);
                    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, result.vertices.size());
                    if (!faces.empty()) {
                        result.preview_normals = compute_smooth_normals(result.vertices, faces);
                    }
                    result.sparse_snapshot_id = sparse_snapshot_id;
                    store_sparse_vertex_snapshot_values(
                        sparse_snapshot_id,
                        result.index,
                        static_cast<int>(result.vertices.size()),
                        result.changed_vertices,
                        result.before_positions
                    );
                }
                if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
                    if (result.topology_changed && !result.append_submesh) {
                        session->vertices = result.vertices;
                        session->faces = result.faces;
                        session->source_face_indices = result.source_face_indices.size() == result.faces.size()
                            ? result.source_face_indices
                            : identity_indices(session->faces.size());
                        session->normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
                        session->uvs = result.preview_uvs.size() == result.vertices.size() ? result.preview_uvs : std::vector<Vec2>();
                        session->tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
                        session->tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
                        if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                            session->bone_indices = result.bones.indices;
                            session->bone_weights = result.bones.weights;
                        } else {
                            session->bone_indices.clear();
                            session->bone_weights.clear();
                        }
                        session->source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
                        session->source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
                    } else if (!result.topology_changed && session->vertices.size() == result.vertices.size()) {
                        session->vertices = result.vertices;
                        session->normals.clear();
                    }
                }
                results.push_back(std::move(result));
            }
        }
    }
    return results;
}

int count_degenerate_uv_faces(
    const std::vector<Vec2>& uvs,
    const std::vector<std::array<int, 3>>& faces
) {
    int count = 0;
    for (const auto& face : faces) {
        const Vec2 uv0 = uvs[static_cast<std::size_t>(face[0])];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(face[1])];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(face[2])];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) <= 1e-12 || !std::isfinite(denom)) {
            ++count;
        }
    }
    return count;
}

void update_tangent_storage_safety(TangentBuildResult& build, std::size_t vertex_count) {
    std::vector<bool> seen(vertex_count, false);
    std::vector<Vec3> first_tangents(vertex_count, {1.0, 0.0, 0.0});
    std::vector<double> first_signs(vertex_count, 1.0);
    std::set<int> split_required;
    for (const FaceCornerTangents& face_corners : build.face_corner_tangents) {
        for (std::size_t corner = 0; corner < face_corners.vertices.size(); ++corner) {
            const int index = face_corners.vertices[corner];
            if (index < 0 || static_cast<std::size_t>(index) >= vertex_count) {
                continue;
            }
            const std::size_t vertex_index = static_cast<std::size_t>(index);
            if (!seen[vertex_index]) {
                seen[vertex_index] = true;
                first_tangents[vertex_index] = face_corners.tangents[corner];
                first_signs[vertex_index] = face_corners.signs[corner];
                continue;
            }
            if (!same_vec3(first_tangents[vertex_index], face_corners.tangents[corner])
                || std::abs(first_signs[vertex_index] - face_corners.signs[corner]) > 1e-8) {
                split_required.insert(index);
            }
        }
    }
    build.split_required_vertices.assign(split_required.begin(), split_required.end());
    build.vertex_storage_safe = build.split_required_vertices.empty();
}

TangentBuildResult compute_tangent_basis_fallback(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<std::array<int, 3>>& faces
) {
    TangentBuildResult build;
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const auto& face = faces[face_index];
        const int a = face[0];
        const int b = face[1];
        const int c = face[2];
        const Vec3 edge1 = sub_vec3(vertices[static_cast<std::size_t>(b)], vertices[static_cast<std::size_t>(a)]);
        const Vec3 edge2 = sub_vec3(vertices[static_cast<std::size_t>(c)], vertices[static_cast<std::size_t>(a)]);
        const Vec2 uv0 = uvs[static_cast<std::size_t>(a)];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(b)];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(c)];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double denom = du1 * dv2 - du2 * dv1;
        if (std::abs(denom) <= 1e-12 || !std::isfinite(denom)) {
            ++build.degenerate_uv_faces;
            continue;
        }
        const Vec3 tangent = scale_vec3(sub_vec3(scale_vec3(edge1, dv2), scale_vec3(edge2, dv1)), 1.0 / denom);
        FaceCornerTangents face_corners;
        face_corners.face_index = static_cast<int>(face_index);
        face_corners.vertices = face;
        for (int corner = 0; corner < 3; ++corner) {
            const int index = face[static_cast<std::size_t>(corner)];
            const Vec3 normal = normals.size() == vertices.size() ? normals[static_cast<std::size_t>(index)] : Vec3{0.0, 0.0, 1.0};
            const Vec3 projected = sub_vec3(tangent, scale_vec3(normal, dot_vec3(normal, tangent)));
            face_corners.tangents[static_cast<std::size_t>(corner)] = normalized_vec3(projected, {1.0, 0.0, 0.0});
            accum[static_cast<std::size_t>(index)] = add_vec3(accum[static_cast<std::size_t>(index)], tangent);
            ++build.face_corner_tangent_count;
        }
        build.face_corner_tangents.push_back(face_corners);
    }

    build.vertex_tangents.reserve(vertices.size());
    for (std::size_t index = 0; index < accum.size(); ++index) {
        const Vec3 normal = normals.size() == vertices.size() ? normals[index] : Vec3{0.0, 0.0, 1.0};
        const Vec3 projected = sub_vec3(accum[index], scale_vec3(normal, dot_vec3(normal, accum[index])));
        build.vertex_tangents.push_back(normalized_vec3(projected, {1.0, 0.0, 0.0}));
    }
    update_tangent_storage_safety(build, vertices.size());
    return build;
}

struct MikkTangentContextData {
    const std::vector<Vec3>* vertices = nullptr;
    const std::vector<Vec2>* uvs = nullptr;
    const std::vector<Vec3>* normals = nullptr;
    const std::vector<std::array<int, 3>>* faces = nullptr;
    std::vector<FaceCornerTangents>* face_corner_tangents = nullptr;
    int face_corner_tangent_count = 0;
};

MikkTangentContextData* mikk_data(const SMikkTSpaceContext* context) {
    return static_cast<MikkTangentContextData*>(context->m_pUserData);
}

int mikk_get_num_faces(const SMikkTSpaceContext* context) {
    const MikkTangentContextData* data = mikk_data(context);
    return data && data->faces ? static_cast<int>(data->faces->size()) : 0;
}

int mikk_get_num_vertices_of_face(const SMikkTSpaceContext*, const int) {
    return 3;
}

void mikk_get_position(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec3& value = (*data->vertices)[static_cast<std::size_t>(index)];
    out[0] = static_cast<float>(value[0]);
    out[1] = static_cast<float>(value[1]);
    out[2] = static_cast<float>(value[2]);
}

void mikk_get_normal(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec3 normal = normalized_vec3((*data->normals)[static_cast<std::size_t>(index)], {0.0, 0.0, 1.0});
    out[0] = static_cast<float>(normal[0]);
    out[1] = static_cast<float>(normal[1]);
    out[2] = static_cast<float>(normal[2]);
}

void mikk_get_tex_coord(const SMikkTSpaceContext* context, float out[], const int face_index, const int vertex_index) {
    const MikkTangentContextData* data = mikk_data(context);
    const int index = (*data->faces)[static_cast<std::size_t>(face_index)][static_cast<std::size_t>(vertex_index)];
    const Vec2& value = (*data->uvs)[static_cast<std::size_t>(index)];
    out[0] = static_cast<float>(value[0]);
    out[1] = static_cast<float>(value[1]);
}

void mikk_set_tspace_basic(
    const SMikkTSpaceContext* context,
    const float tangent[],
    const float sign,
    const int face_index,
    const int vertex_index
) {
    MikkTangentContextData* data = mikk_data(context);
    if (data == nullptr || data->face_corner_tangents == nullptr) {
        return;
    }
    if (face_index < 0 || vertex_index < 0 || vertex_index >= 3 || static_cast<std::size_t>(face_index) >= data->face_corner_tangents->size()) {
        return;
    }
    FaceCornerTangents& face_corners = (*data->face_corner_tangents)[static_cast<std::size_t>(face_index)];
    face_corners.tangents[static_cast<std::size_t>(vertex_index)] = normalized_vec3(
        {static_cast<double>(tangent[0]), static_cast<double>(tangent[1]), static_cast<double>(tangent[2])},
        {1.0, 0.0, 0.0}
    );
    face_corners.signs[static_cast<std::size_t>(vertex_index)] = sign >= 0.0f ? 1.0 : -1.0;
    ++data->face_corner_tangent_count;
}

TangentBuildResult compute_tangent_basis(
    const std::vector<Vec3>& vertices,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<std::array<int, 3>>& faces
) {
    TangentBuildResult build;
    build.tangent_backend = "mikktspace_reference";
    build.degenerate_uv_faces = count_degenerate_uv_faces(uvs, faces);
    build.face_corner_tangents.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        FaceCornerTangents face_corners;
        face_corners.face_index = static_cast<int>(face_index);
        face_corners.vertices = faces[face_index];
        build.face_corner_tangents.push_back(face_corners);
    }

    MikkTangentContextData data;
    data.vertices = &vertices;
    data.uvs = &uvs;
    data.normals = &normals;
    data.faces = &faces;
    data.face_corner_tangents = &build.face_corner_tangents;

    SMikkTSpaceInterface interface_callbacks = {};
    interface_callbacks.m_getNumFaces = mikk_get_num_faces;
    interface_callbacks.m_getNumVerticesOfFace = mikk_get_num_vertices_of_face;
    interface_callbacks.m_getPosition = mikk_get_position;
    interface_callbacks.m_getNormal = mikk_get_normal;
    interface_callbacks.m_getTexCoord = mikk_get_tex_coord;
    interface_callbacks.m_setTSpaceBasic = mikk_set_tspace_basic;

    SMikkTSpaceContext context = {};
    context.m_pInterface = &interface_callbacks;
    context.m_pUserData = &data;

    if (!genTangSpaceDefault(&context)) {
        return compute_tangent_basis_fallback(vertices, uvs, normals, faces);
    }

    build.face_corner_tangent_count = data.face_corner_tangent_count;
    std::vector<Vec3> accum(vertices.size(), {0.0, 0.0, 0.0});
    std::vector<int> counts(vertices.size(), 0);
    for (const FaceCornerTangents& face_corners : build.face_corner_tangents) {
        for (std::size_t corner = 0; corner < face_corners.vertices.size(); ++corner) {
            const int index = face_corners.vertices[corner];
            if (0 <= index && static_cast<std::size_t>(index) < accum.size()) {
                accum[static_cast<std::size_t>(index)] = add_vec3(accum[static_cast<std::size_t>(index)], face_corners.tangents[corner]);
                ++counts[static_cast<std::size_t>(index)];
            }
        }
    }
    build.vertex_tangents.reserve(vertices.size());
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        build.vertex_tangents.push_back(
            counts[index] > 0 ? normalized_vec3(accum[index], {1.0, 0.0, 0.0}) : Vec3{1.0, 0.0, 0.0}
        );
    }
    update_tangent_storage_safety(build, vertices.size());
    return build;
}

bool build_tangent_split_result(
    const JsonValue& item,
    const std::vector<Vec3>& source_vertices,
    const std::vector<Vec2>& source_uvs,
    const std::vector<Vec3>& source_normals,
    const std::vector<std::array<int, 3>>& source_faces,
    const TangentBuildResult& build,
    SubmeshTangentsResult& result
) {
    if (result.vertices_path.empty()
        || result.faces_path.empty()
        || result.uvs_path.empty()
        || result.normals_path.empty()
        || result.tangents_path.empty()
        || result.tangent_signs_path.empty()) {
        return false;
    }
    if (source_vertices.empty()
        || source_uvs.size() != source_vertices.size()
        || source_normals.size() != source_vertices.size()
        || build.face_corner_tangents.size() != source_faces.size()) {
        return false;
    }

    BoneAssignments source_bones = mesh_bones_from_item(item);
    const bool has_bones = valid_bone_assignments(source_bones)
        && source_bones.indices.size() == source_vertices.size()
        && source_bones.weights.size() == source_vertices.size()
        && !result.bone_counts_path.empty()
        && !result.bone_indices_path.empty()
        && !result.bone_weights_path.empty();
    std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
        item,
        "source_vertex_map_binary",
        "source_vertex_map",
        "source_vertex_map_start",
        "source_vertex_map_count"
    );
    std::vector<int> source_vertex_offsets = source_vertex_offsets_from_item(item);
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        if (source_vertex_map.empty()) {
            source_vertex_map = session->source_vertex_map;
        }
        if (source_vertex_offsets.empty()) {
            source_vertex_offsets = session->source_vertex_offsets;
        }
    }
    const bool has_source_vertex_map = source_vertex_map.size() == source_vertices.size() && !result.source_vertex_map_path.empty();
    const bool has_source_vertex_offsets = source_vertex_offsets.size() == source_vertices.size() && !result.source_vertex_offsets_path.empty();

    std::map<std::tuple<int, double, double, double, double>, int> corner_index_by_key;
    std::vector<Vec3> split_vertices;
    std::vector<Vec2> split_uvs;
    std::vector<Vec3> split_normals;
    std::vector<Vec3> split_tangents;
    std::vector<double> split_tangent_signs;
    std::vector<std::array<int, 3>> split_faces;
    BoneAssignments split_bones;
    std::vector<int> split_source_vertex_map;
    std::vector<int> split_source_vertex_offsets;

    split_faces.reserve(source_faces.size());
    for (std::size_t face_index = 0; face_index < source_faces.size(); ++face_index) {
        const FaceCornerTangents& face_corners = build.face_corner_tangents[face_index];
        if (face_corners.face_index != static_cast<int>(face_index) || face_corners.vertices != source_faces[face_index]) {
            return false;
        }
        std::array<int, 3> split_face{0, 0, 0};
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const int old_index = face_corners.vertices[corner];
            if (old_index < 0 || static_cast<std::size_t>(old_index) >= source_vertices.size()) {
                return false;
            }
            const Vec3 tangent = face_corners.tangents[corner];
            const double sign = face_corners.signs[corner] >= 0.0 ? 1.0 : -1.0;
            const auto key = std::make_tuple(old_index, tangent[0], tangent[1], tangent[2], sign);
            auto existing = corner_index_by_key.find(key);
            int new_index = -1;
            if (existing != corner_index_by_key.end()) {
                new_index = existing->second;
            } else {
                if (split_vertices.size() >= static_cast<std::size_t>(INT_MAX)) {
                    return false;
                }
                new_index = static_cast<int>(split_vertices.size());
                corner_index_by_key[key] = new_index;
                const std::size_t source_index = static_cast<std::size_t>(old_index);
                split_vertices.push_back(source_vertices[source_index]);
                split_uvs.push_back(source_uvs[source_index]);
                split_normals.push_back(source_normals[source_index]);
                split_tangents.push_back(tangent);
                split_tangent_signs.push_back(sign);
                if (has_bones) {
                    split_bones.indices.push_back(source_bones.indices[source_index]);
                    split_bones.weights.push_back(source_bones.weights[source_index]);
                }
                if (has_source_vertex_map) {
                    split_source_vertex_map.push_back(source_vertex_map[source_index]);
                }
                if (has_source_vertex_offsets) {
                    split_source_vertex_offsets.push_back(source_vertex_offsets[source_index]);
                }
            }
            split_face[corner] = new_index;
        }
        split_faces.push_back(split_face);
    }

    result.vertices = std::move(split_vertices);
    result.faces = std::move(split_faces);
    result.uvs = std::move(split_uvs);
    result.normals = std::move(split_normals);
    result.tangents = std::move(split_tangents);
    result.tangent_signs = std::move(split_tangent_signs);
    result.bones = std::move(split_bones);
    result.source_vertex_map = std::move(split_source_vertex_map);
    result.source_vertex_offsets = std::move(split_source_vertex_offsets);
    result.topology_split_applied = result.vertices.size() == result.tangents.size()
        && result.vertices.size() == result.tangent_signs.size()
        && result.vertices.size() == result.uvs.size()
        && result.vertices.size() == result.normals.size();
    return result.topology_split_applied;
}

std::vector<SubmeshTangentsResult> run_generate_tangents(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshTangentsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty() || uvs.size() != vertices.size() || faces.empty()) {
            continue;
        }
        if (normals.size() != vertices.size()) {
            normals = compute_smooth_normals(vertices, faces);
        }
        SubmeshTangentsResult result;
        result.index = index;
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.tangents_path = string_or(item.get("tangents_output_path"), "");
        result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        TangentBuildResult build = compute_tangent_basis(
            vertices,
            uvs,
            normals,
            faces
        );
        result.tangent_backend = build.tangent_backend;
        result.tangents = build.vertex_tangents;
        const std::vector<Vec3> existing_tangents = mesh_tangents_from_item(item);
        if (existing_tangents.size() == result.tangents.size()) {
            for (std::size_t tangent_index = 0; tangent_index < result.tangents.size(); ++tangent_index) {
                if (!same_vec3(existing_tangents[tangent_index], result.tangents[tangent_index])) {
                    result.changed_vertices.push_back(static_cast<int>(tangent_index));
                }
            }
        } else {
            result.changed_vertices.reserve(result.tangents.size());
            for (std::size_t tangent_index = 0; tangent_index < result.tangents.size(); ++tangent_index) {
                result.changed_vertices.push_back(static_cast<int>(tangent_index));
            }
        }
        result.split_required_vertices = std::move(build.split_required_vertices);
        result.face_corner_tangent_count = build.face_corner_tangent_count;
        result.degenerate_uv_faces = build.degenerate_uv_faces;
        result.vertex_storage_safe = build.vertex_storage_safe;
        if (!build.vertex_storage_safe) {
            build_tangent_split_result(item, vertices, uvs, normals, faces, build, result);
        }
        if (!result.topology_split_applied) {
            result.face_corner_tangents = std::move(build.face_corner_tangents);
        }
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            if (result.topology_split_applied) {
                session->vertices = result.vertices;
                session->faces = result.faces;
                session->normals = result.normals;
                session->uvs = result.uvs;
                session->tangents = result.tangents;
                session->tangent_signs = result.tangent_signs;
                if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
                    session->bone_indices = result.bones.indices;
                    session->bone_weights = result.bones.weights;
                }
                if (result.source_vertex_map.size() == result.vertices.size()) {
                    session->source_vertex_map = result.source_vertex_map;
                }
                if (result.source_vertex_offsets.size() == result.vertices.size()) {
                    session->source_vertex_offsets = result.source_vertex_offsets;
                }
            } else if (session->vertices.size() == result.tangents.size()) {
                session->tangents = result.tangents;
            }
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<Vec3> morph_delta_for_submesh(const JsonValue& delta_item, int submesh_index) {
    const JsonValue* delta_submeshes = delta_item.get("submeshes");
    if (delta_submeshes == nullptr || delta_submeshes->type != JsonValue::Type::Array) {
        return {};
    }
    for (const JsonValue& item : delta_submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        if (int_or(item.get("index"), -1) == submesh_index) {
            return vertices_from_binary_or_json(item, "deltas_binary", "deltas");
        }
    }
    return {};
}

std::map<int, double> region_volume_selection_weights(
    std::size_t vertex_count,
    const std::vector<std::array<int, 3>>& faces,
    const std::set<int>& selected,
    int feather
) {
    std::map<int, double> weights;
    for (const int index : selected) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            weights[index] = 1.0;
        }
    }
    const int rings = std::max(0, feather);
    if (weights.empty() || rings <= 0) {
        return weights;
    }
    const std::vector<std::set<int>> adjacency = build_vertex_adjacency(vertex_count, faces);
    std::set<int> frontier;
    std::set<int> visited;
    for (const auto& item : weights) {
        frontier.insert(item.first);
        visited.insert(item.first);
    }
    for (int depth = 1; depth <= rings; ++depth) {
        std::set<int> next_frontier;
        for (const int index : frontier) {
            if (index < 0 || static_cast<std::size_t>(index) >= adjacency.size()) {
                continue;
            }
            for (const int neighbor : adjacency[static_cast<std::size_t>(index)]) {
                if (visited.find(neighbor) == visited.end()) {
                    next_frontier.insert(neighbor);
                }
            }
        }
        if (next_frontier.empty()) {
            break;
        }
        const double weight = std::max(0.0, 1.0 - (static_cast<double>(depth) / static_cast<double>(rings + 1)));
        for (const int index : next_frontier) {
            auto found = weights.find(index);
            if (found == weights.end() || found->second < weight) {
                weights[index] = weight;
            }
            visited.insert(index);
        }
        frontier = std::move(next_frontier);
    }
    return weights;
}

std::vector<SubmeshRegionVolumeDeltaResult> run_region_volume_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const double amount = number_or(root.get("amount"), 0.0);
    const int feather = std::max(0, int_or(root.get("feather"), 0));
    std::vector<SubmeshRegionVolumeDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (index < 0 || vertices.empty()) {
            continue;
        }
        std::set<int> selected = selected_vertices_from_binary_or_json(item, vertices.size());
        std::map<int, double> weights = region_volume_selection_weights(vertices.size(), faces, selected, feather);
        Vec3 center{0.0, 0.0, 0.0};
        for (const auto& entry : weights) {
            const Vec3& vertex = vertices[static_cast<std::size_t>(entry.first)];
            center[0] += vertex[0];
            center[1] += vertex[1];
            center[2] += vertex[2];
        }
        if (!weights.empty()) {
            const double denominator = static_cast<double>(weights.size());
            center = {center[0] / denominator, center[1] / denominator, center[2] / denominator};
        }
        const std::vector<Vec3> normals = compute_smooth_normals(vertices, faces);
        SubmeshRegionVolumeDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(vertices.size());
        result.selected_vertex_count = static_cast<int>(selected.size());
        result.weighted_vertex_count = static_cast<int>(weights.size());
        result.deltas.reserve(vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
            double weight = 0.0;
            const auto found = weights.find(static_cast<int>(vertex_index));
            if (found != weights.end()) {
                weight = std::max(0.0, std::min(1.0, found->second));
            }
            if (weight <= 0.0) {
                result.deltas.push_back({0.0, 0.0, 0.0});
                continue;
            }
            const Vec3 radial = normalized_vec3(sub_vec3(vertices[vertex_index], center), {0.0, 1.0, 0.0});
            const Vec3 normal = vertex_index < normals.size() ? normalized_vec3(normals[vertex_index], radial) : radial;
            result.deltas.push_back(scale_vec3(normal, amount * weight));
        }
        write_vec3_binary_file(result.deltas_path, result.deltas);
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphApplyResult> run_morph_apply(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const JsonValue* deltas = root.get("deltas");
    std::vector<SubmeshMorphApplyResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (deltas != nullptr && deltas->type == JsonValue::Type::Array) {
            for (const JsonValue& delta_item : deltas->array_value) {
                if (delta_item.type != JsonValue::Type::Object) {
                    continue;
                }
                const double factor = number_or(delta_item.get("factor"), 0.0);
                if (std::abs(factor) <= 1e-15) {
                    continue;
                }
                const std::vector<Vec3> delta_vertices = morph_delta_for_submesh(delta_item, index);
                const std::size_t count = std::min(vertices.size(), delta_vertices.size());
                for (std::size_t vertex_index = 0; vertex_index < count; ++vertex_index) {
                    vertices[vertex_index][0] += delta_vertices[vertex_index][0] * factor;
                    vertices[vertex_index][1] += delta_vertices[vertex_index][1] * factor;
                    vertices[vertex_index][2] += delta_vertices[vertex_index][2] * factor;
                }
            }
        }
        const std::vector<Vec3> post_edit_deltas = vertices_from_binary_or_json(item, "post_edit_deltas_binary", "post_edit_deltas");
        const std::size_t post_count = std::min(vertices.size(), post_edit_deltas.size());
        for (std::size_t vertex_index = 0; vertex_index < post_count; ++vertex_index) {
            vertices[vertex_index][0] += post_edit_deltas[vertex_index][0];
            vertices[vertex_index][1] += post_edit_deltas[vertex_index][1];
            vertices[vertex_index][2] += post_edit_deltas[vertex_index][2];
        }
        for (const Vec3& vertex : vertices) {
            if (!std::isfinite(vertex[0]) || !std::isfinite(vertex[1]) || !std::isfinite(vertex[2])) {
                throw std::runtime_error("non-finite morph output vertex");
            }
        }
        const std::vector<Vec3> normals = compute_smooth_normals(vertices, faces);
        const std::string vertices_path = string_or(item.get("output_vertices_path"), "");
        const std::string normals_path = string_or(item.get("output_normals_path"), "");
        write_vec3_binary_file(vertices_path, vertices);
        write_vec3_binary_file(normals_path, normals);

        SubmeshMorphApplyResult result;
        result.index = index;
        result.vertices_path = vertices_path;
        result.normals_path = normals_path;
        result.vertex_count = static_cast<int>(vertices.size());
        result.normal_count = static_cast<int>(normals.size());
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphPostEditDeltaResult> run_morph_post_edit_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMorphPostEditDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> working_vertices =
            vertices_from_binary_or_json(item, "working_vertices_binary", "working_vertices");
        const std::vector<Vec3> slider_vertices =
            vertices_from_binary_or_json(item, "slider_vertices_binary", "slider_vertices");
        if (working_vertices.size() != slider_vertices.size()) {
            throw std::runtime_error("morph post-edit vertex count mismatch");
        }
        SubmeshMorphPostEditDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(working_vertices.size());
        result.zero_delta = true;
        result.deltas.reserve(working_vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < working_vertices.size(); ++vertex_index) {
            Vec3 delta{
                working_vertices[vertex_index][0] - slider_vertices[vertex_index][0],
                working_vertices[vertex_index][1] - slider_vertices[vertex_index][1],
                working_vertices[vertex_index][2] - slider_vertices[vertex_index][2],
            };
            if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
                throw std::runtime_error("non-finite morph post-edit delta");
            }
            if (delta[0] != 0.0 || delta[1] != 0.0 || delta[2] != 0.0) {
                result.zero_delta = false;
            }
            result.deltas.push_back(delta);
        }
        if (!result.zero_delta) {
            write_vec3_binary_file(result.deltas_path, result.deltas);
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshMorphPostEditDeltaResult> run_morph_target_delta(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshMorphPostEditDeltaResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> base_vertices =
            vertices_from_binary_or_json(item, "base_vertices_binary", "base_vertices");
        const std::vector<Vec3> target_vertices =
            vertices_from_binary_or_json(item, "target_vertices_binary", "target_vertices");
        if (base_vertices.size() != target_vertices.size()) {
            throw std::runtime_error("morph target vertex count mismatch");
        }
        const std::vector<std::array<int, 3>> base_faces =
            faces_from_binary_or_json_keys(item, "base_faces_binary", "base_faces", base_vertices.size());
        const std::vector<std::array<int, 3>> target_faces =
            faces_from_binary_or_json_keys(item, "target_faces_binary", "target_faces", target_vertices.size());
        if (base_faces.size() != target_faces.size()) {
            throw std::runtime_error("morph target face count mismatch");
        }
        if (base_faces != target_faces) {
            throw std::runtime_error("morph target face topology mismatch");
        }
        SubmeshMorphPostEditDeltaResult result;
        result.index = index;
        result.deltas_path = string_or(item.get("deltas_output_path"), "");
        result.vertex_count = static_cast<int>(base_vertices.size());
        result.deltas.reserve(base_vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < base_vertices.size(); ++vertex_index) {
            Vec3 delta{
                target_vertices[vertex_index][0] - base_vertices[vertex_index][0],
                target_vertices[vertex_index][1] - base_vertices[vertex_index][1],
                target_vertices[vertex_index][2] - base_vertices[vertex_index][2],
            };
            if (!std::isfinite(delta[0]) || !std::isfinite(delta[1]) || !std::isfinite(delta[2])) {
                throw std::runtime_error("non-finite morph target delta");
            }
            result.deltas.push_back(delta);
        }
        write_vec3_binary_file(result.deltas_path, result.deltas);
        results.push_back(std::move(result));
    }
    return results;
}

std::pair<Vec3, Vec3> static_donor_bbox(const std::vector<Vec3>& vertices) {
    if (vertices.empty()) {
        return {Vec3{0.0, 0.0, 0.0}, Vec3{1.0, 1.0, 1.0}};
    }
    Vec3 bbox_min = vertices.front();
    Vec3 bbox_max = vertices.front();
    for (const Vec3& vertex : vertices) {
        bbox_min[0] = std::min(bbox_min[0], vertex[0]);
        bbox_min[1] = std::min(bbox_min[1], vertex[1]);
        bbox_min[2] = std::min(bbox_min[2], vertex[2]);
        bbox_max[0] = std::max(bbox_max[0], vertex[0]);
        bbox_max[1] = std::max(bbox_max[1], vertex[1]);
        bbox_max[2] = std::max(bbox_max[2], vertex[2]);
    }
    constexpr double eps = 1.0e-6;
    bbox_min[0] -= eps;
    bbox_min[1] -= eps;
    bbox_min[2] -= eps;
    bbox_max[0] += eps;
    bbox_max[1] += eps;
    bbox_max[2] += eps;
    return {bbox_min, bbox_max};
}

double static_alignment_match_cost(
    const Vec3& orig_vertex,
    const Vec3& new_vertex,
    int orig_index,
    int new_index,
    double diag,
    int max_count
) {
    double dist = std::sqrt(distance_squared_vec3(orig_vertex, new_vertex));
    if (orig_index == new_index) {
        dist *= 0.75;
    } else if (std::abs(orig_index - new_index) <= 2) {
        dist *= 0.85;
    }
    const double order_penalty =
        (static_cast<double>(std::abs(orig_index - new_index)) / static_cast<double>(std::max(max_count, 1)))
        * std::max(diag * 0.05, 0.01);
    return dist + order_penalty;
}

std::vector<int> align_static_donor_vertex_sequences(
    const std::vector<Vec3>& orig_vertices,
    const std::vector<Vec3>& new_vertices
) {
    const int orig_count = static_cast<int>(orig_vertices.size());
    const int new_count = static_cast<int>(new_vertices.size());
    std::vector<int> aligned(static_cast<std::size_t>(new_count), -1);
    if (orig_count == 0 || new_count == 0) {
        return aligned;
    }

    const auto bbox = static_donor_bbox(orig_vertices);
    const double diag = std::sqrt(distance_squared_vec3(bbox.first, bbox.second));
    const double gap_penalty = std::max(diag * 0.02, 0.01);
    const int band = std::max(128, std::abs(orig_count - new_count) + 128);
    const long long max_states =
        static_cast<long long>(orig_count + 1) * static_cast<long long>(std::min(new_count + 1, band * 2 + 1));
    if (max_states > 3000000LL) {
        throw std::runtime_error("Static vertex alignment too large");
    }

    std::map<int, double> prev_row;
    const int first_row_end = std::min(new_count, band);
    for (int j = 0; j <= first_row_end; ++j) {
        prev_row[j] = static_cast<double>(j) * gap_penalty;
    }
    std::map<std::pair<int, int>, char> backtrack;
    for (int j = 1; j <= first_row_end; ++j) {
        backtrack[{0, j}] = 'l';
    }

    const int max_count = std::max(orig_count, new_count);
    for (int i = 1; i <= orig_count; ++i) {
        const int j_start = std::max(0, i - band);
        const int j_end = std::min(new_count, i + band);
        std::map<int, double> curr_row;
        if (j_start == 0) {
            curr_row[0] = static_cast<double>(i) * gap_penalty;
            backtrack[{i, 0}] = 'u';
        }

        for (int j = std::max(1, j_start); j <= j_end; ++j) {
            double best_cost = 1.0e300;
            char best_move = '\0';

            const auto diag_prev = prev_row.find(j - 1);
            if (diag_prev != prev_row.end()) {
                const double cost = diag_prev->second + static_alignment_match_cost(
                    orig_vertices[static_cast<std::size_t>(i - 1)],
                    new_vertices[static_cast<std::size_t>(j - 1)],
                    i - 1,
                    j - 1,
                    diag,
                    max_count
                );
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'd';
                }
            }

            const auto up_prev = prev_row.find(j);
            if (up_prev != prev_row.end()) {
                const double cost = up_prev->second + gap_penalty;
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'u';
                }
            }

            const auto left_prev = curr_row.find(j - 1);
            if (left_prev != curr_row.end()) {
                const double cost = left_prev->second + gap_penalty;
                if (cost < best_cost) {
                    best_cost = cost;
                    best_move = 'l';
                }
            }

            if (best_move != '\0') {
                curr_row[j] = best_cost;
                backtrack[{i, j}] = best_move;
            }
        }
        prev_row = std::move(curr_row);
    }

    if (prev_row.find(new_count) == prev_row.end()) {
        throw std::runtime_error("Static vertex alignment band did not reach the final state");
    }

    int i = orig_count;
    int j = new_count;
    while (i > 0 || j > 0) {
        const auto found = backtrack.find({i, j});
        const char move = found == backtrack.end() ? '\0' : found->second;
        if (move == 'd') {
            aligned[static_cast<std::size_t>(j - 1)] = i - 1;
            --i;
            --j;
        } else if (move == 'l') {
            --j;
        } else if (move == 'u') {
            --i;
        } else {
            if (j > 0 && i > 0) {
                aligned[static_cast<std::size_t>(j - 1)] = i - 1;
                --i;
                --j;
            } else if (j > 0) {
                --j;
            } else {
                --i;
            }
        }
    }
    return aligned;
}

long long static_donor_round_key(double value) {
    return static_cast<long long>(std::nearbyint(value * 100000.0));
}

std::tuple<long long, long long, long long> static_donor_rounded_key(const Vec3& vertex) {
    return {
        static_donor_round_key(vertex[0]),
        static_donor_round_key(vertex[1]),
        static_donor_round_key(vertex[2])
    };
}

std::tuple<int, int, int> static_donor_cell_key(const Vec3& vertex, double cell_size) {
    return {
        static_cast<int>(std::floor(vertex[0] / cell_size)),
        static_cast<int>(std::floor(vertex[1] / cell_size)),
        static_cast<int>(std::floor(vertex[2] / cell_size))
    };
}

std::pair<double, std::map<std::tuple<int, int, int>, std::vector<int>>> build_static_donor_spatial_hash(
    const std::vector<Vec3>& points
) {
    if (points.empty()) {
        return {1.0, {}};
    }
    Vec3 bbox_min = points.front();
    Vec3 bbox_max = points.front();
    for (const Vec3& point : points) {
        bbox_min[0] = std::min(bbox_min[0], point[0]);
        bbox_min[1] = std::min(bbox_min[1], point[1]);
        bbox_min[2] = std::min(bbox_min[2], point[2]);
        bbox_max[0] = std::max(bbox_max[0], point[0]);
        bbox_max[1] = std::max(bbox_max[1], point[1]);
        bbox_max[2] = std::max(bbox_max[2], point[2]);
    }
    const double extent = std::max(
        std::max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1]),
        std::max(bbox_max[2] - bbox_min[2], 1.0e-5)
    );
    const int divisions = std::max(static_cast<int>(std::nearbyint(std::pow(static_cast<double>(points.size()), 1.0 / 3.0))), 1);
    const double cell_size = std::max(extent / static_cast<double>(divisions), 1.0e-5);
    std::map<std::tuple<int, int, int>, std::vector<int>> grid;
    for (std::size_t index = 0; index < points.size(); ++index) {
        grid[static_donor_cell_key(points[index], cell_size)].push_back(static_cast<int>(index));
    }
    return {cell_size, std::move(grid)};
}

int nearest_static_donor_point_index(
    const Vec3& point,
    const std::vector<Vec3>& source_points,
    double cell_size,
    const std::map<std::tuple<int, int, int>, std::vector<int>>& grid
) {
    if (source_points.empty()) {
        throw std::runtime_error("Cannot transfer displacement from an empty source mesh.");
    }
    const auto base = static_donor_cell_key(point, cell_size);
    const int base_x = std::get<0>(base);
    const int base_y = std::get<1>(base);
    const int base_z = std::get<2>(base);
    int best_index = -1;
    double best_d2 = 1.0e300;

    for (int radius = 0; radius < 8; ++radius) {
        bool found_any = false;
        for (int dx = -radius; dx <= radius; ++dx) {
            for (int dy = -radius; dy <= radius; ++dy) {
                for (int dz = -radius; dz <= radius; ++dz) {
                    const auto found = grid.find({base_x + dx, base_y + dy, base_z + dz});
                    if (found == grid.end()) {
                        continue;
                    }
                    for (const int index : found->second) {
                        found_any = true;
                        const double d2 = distance_squared_vec3(source_points[static_cast<std::size_t>(index)], point);
                        if (d2 < best_d2) {
                            best_d2 = d2;
                            best_index = index;
                        }
                    }
                }
            }
        }
        if (found_any && best_index >= 0) {
            return best_index;
        }
    }

    for (std::size_t index = 0; index < source_points.size(); ++index) {
        const double d2 = distance_squared_vec3(source_points[index], point);
        if (d2 < best_d2) {
            best_d2 = d2;
            best_index = static_cast<int>(index);
        }
    }
    return best_index;
}

std::vector<int> choose_static_donor_indices_native(
    const std::vector<Vec3>& orig_vertices,
    const std::vector<Vec3>& new_vertices,
    bool& sequence_alignment_used,
    bool& sequence_alignment_fallback
) {
    sequence_alignment_used = false;
    sequence_alignment_fallback = false;
    if (new_vertices.empty()) {
        return {};
    }
    if (orig_vertices.empty()) {
        return std::vector<int>(new_vertices.size(), 0);
    }

    std::vector<int> donor_indices;
    try {
        donor_indices = align_static_donor_vertex_sequences(orig_vertices, new_vertices);
        sequence_alignment_used = true;
    } catch (const std::exception&) {
        donor_indices.assign(new_vertices.size(), -1);
        sequence_alignment_fallback = true;
    }

    std::map<std::tuple<long long, long long, long long>, std::vector<int>> rounded_map;
    for (std::size_t orig_index = 0; orig_index < orig_vertices.size(); ++orig_index) {
        rounded_map[static_donor_rounded_key(orig_vertices[orig_index])].push_back(static_cast<int>(orig_index));
    }

    const auto spatial = build_static_donor_spatial_hash(orig_vertices);
    for (std::size_t new_index = 0; new_index < new_vertices.size(); ++new_index) {
        if (0 <= donor_indices[new_index] && static_cast<std::size_t>(donor_indices[new_index]) < orig_vertices.size()) {
            continue;
        }
        const auto exact_hits = rounded_map.find(static_donor_rounded_key(new_vertices[new_index]));
        if (exact_hits != rounded_map.end() && !exact_hits->second.empty()) {
            int best_index = exact_hits->second.front();
            int best_delta = std::abs(best_index - static_cast<int>(new_index));
            for (const int candidate : exact_hits->second) {
                const int delta = std::abs(candidate - static_cast<int>(new_index));
                if (delta < best_delta) {
                    best_index = candidate;
                    best_delta = delta;
                }
            }
            donor_indices[new_index] = best_index;
            continue;
        }
        donor_indices[new_index] = nearest_static_donor_point_index(
            new_vertices[new_index],
            orig_vertices,
            spatial.first,
            spatial.second
        );
    }
    return donor_indices;
}

std::vector<SubmeshStaticDonorIndicesResult> run_static_donor_indices(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshStaticDonorIndicesResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        const std::vector<Vec3> original_vertices =
            vertices_from_binary_or_json(item, "original_vertices_binary", "original_vertices");
        const std::vector<Vec3> new_vertices =
            vertices_from_binary_or_json(item, "new_vertices_binary", "new_vertices");
        SubmeshStaticDonorIndicesResult result;
        result.index = index;
        result.original_vertex_count = static_cast<int>(original_vertices.size());
        result.new_vertex_count = static_cast<int>(new_vertices.size());
        result.donor_indices_path = string_or(item.get("donor_indices_output_path"), "");
        result.donor_indices = choose_static_donor_indices_native(
            original_vertices,
            new_vertices,
            result.sequence_alignment_used,
            result.sequence_alignment_fallback
        );
        if (static_cast<int>(result.donor_indices.size()) != result.new_vertex_count) {
            throw std::runtime_error("static donor index count mismatch");
        }
        write_int_binary_file(result.donor_indices_path, result.donor_indices);
        results.push_back(std::move(result));
    }
    return results;
}

using PoseMatrix4 = std::array<double, 16>;

PoseMatrix4 pose_identity_matrix() {
    return {
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
}

PoseMatrix4 pose_transpose_matrix(const PoseMatrix4& matrix) {
    PoseMatrix4 result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            result[static_cast<std::size_t>(row * 4 + column)] =
                matrix[static_cast<std::size_t>(column * 4 + row)];
        }
    }
    return result;
}

bool pose_matrix4_from_json(const JsonValue* value, PoseMatrix4& out) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() != 16) {
        return false;
    }
    bool nonzero = false;
    PoseMatrix4 matrix{};
    for (std::size_t index = 0; index < 16; ++index) {
        const JsonValue& raw = value->array_value[index];
        if (raw.type != JsonValue::Type::Number || !std::isfinite(raw.number_value)) {
            return false;
        }
        matrix[index] = raw.number_value;
        nonzero = nonzero || std::fabs(raw.number_value) > 1e-12;
    }
    if (!nonzero) {
        return false;
    }
    const double column_translation = std::fabs(matrix[3]) + std::fabs(matrix[7]) + std::fabs(matrix[11]);
    const double row_translation = std::fabs(matrix[12]) + std::fabs(matrix[13]) + std::fabs(matrix[14]);
    out = row_translation > column_translation && column_translation <= 1e-6
        ? pose_transpose_matrix(matrix)
        : matrix;
    return true;
}

PoseMatrix4 pose_translation_matrix(const Vec3& position) {
    return {
        1.0, 0.0, 0.0, position[0],
        0.0, 1.0, 0.0, position[1],
        0.0, 0.0, 1.0, position[2],
        0.0, 0.0, 0.0, 1.0,
    };
}

PoseMatrix4 pose_matrix_multiply(const PoseMatrix4& left, const PoseMatrix4& right) {
    PoseMatrix4 result{};
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            double value = 0.0;
            for (int mid = 0; mid < 4; ++mid) {
                value += left[static_cast<std::size_t>(row * 4 + mid)]
                    * right[static_cast<std::size_t>(mid * 4 + column)];
            }
            result[static_cast<std::size_t>(row * 4 + column)] = value;
        }
    }
    return result;
}

PoseMatrix4 pose_invert_rigid_affine(const PoseMatrix4& matrix) {
    const double r00 = matrix[0], r01 = matrix[1], r02 = matrix[2], tx = matrix[3];
    const double r10 = matrix[4], r11 = matrix[5], r12 = matrix[6], ty = matrix[7];
    const double r20 = matrix[8], r21 = matrix[9], r22 = matrix[10], tz = matrix[11];
    return {
        r00, r10, r20, -(r00 * tx + r10 * ty + r20 * tz),
        r01, r11, r21, -(r01 * tx + r11 * ty + r21 * tz),
        r02, r12, r22, -(r02 * tx + r12 * ty + r22 * tz),
        0.0, 0.0, 0.0, 1.0,
    };
}

PoseMatrix4 pose_euler_rotation_matrix(const Vec3& rotation_degrees) {
    constexpr double pi = 3.141592653589793238462643383279502884;
    const double x = rotation_degrees[0] * pi / 180.0;
    const double y = rotation_degrees[1] * pi / 180.0;
    const double z = rotation_degrees[2] * pi / 180.0;
    const double cx = std::cos(x), sx = std::sin(x);
    const double cy = std::cos(y), sy = std::sin(y);
    const double cz = std::cos(z), sz = std::sin(z);
    const PoseMatrix4 rx = {
        1.0, 0.0, 0.0, 0.0,
        0.0, cx, -sx, 0.0,
        0.0, sx, cx, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    const PoseMatrix4 ry = {
        cy, 0.0, sy, 0.0,
        0.0, 1.0, 0.0, 0.0,
        -sy, 0.0, cy, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    const PoseMatrix4 rz = {
        cz, -sz, 0.0, 0.0,
        sz, cz, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    };
    return pose_matrix_multiply(rz, pose_matrix_multiply(ry, rx));
}

Vec3 pose_transform_point(const PoseMatrix4& matrix, const Vec3& point) {
    const double x = point[0], y = point[1], z = point[2];
    return {
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    };
}

std::vector<NativePoseBone> pose_bones_from_json(const JsonValue* value) {
    std::vector<NativePoseBone> bones;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return bones;
    }
    bones.reserve(value->array_value.size());
    for (std::size_t ordinal = 0; ordinal < value->array_value.size(); ++ordinal) {
        const JsonValue& item = value->array_value[ordinal];
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        NativePoseBone bone;
        bone.index = int_or(item.get("index"), static_cast<int>(ordinal));
        if (bone.index < 0) {
            bone.index = static_cast<int>(ordinal);
        }
        bone.parent_index = int_or(item.get("parent_index"), -1);
        bone.position = vec3_or(item.get("position"), Vec3{0.0, 0.0, 0.0});
        bone.has_bind_matrix = pose_matrix4_from_json(item.get("bind_matrix"), bone.bind_matrix);
        bone.has_inv_bind_matrix = pose_matrix4_from_json(item.get("inv_bind_matrix"), bone.inv_bind_matrix);
        bones.push_back(bone);
    }
    return bones;
}

std::map<int, Vec3> pose_rotations_from_json(const JsonValue* value) {
    std::map<int, Vec3> rotations;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return rotations;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("bone_index"), int_or(item.get("index"), -1));
        if (index < 0) {
            continue;
        }
        const Vec3 rotation = vec3_or(item.get("rotation_degrees"), Vec3{0.0, 0.0, 0.0});
        if (std::fabs(rotation[0]) <= 1e-6 && std::fabs(rotation[1]) <= 1e-6 && std::fabs(rotation[2]) <= 1e-6) {
            continue;
        }
        rotations[index] = rotation;
    }
    return rotations;
}

std::map<int, PoseMatrix4> pose_skinning_matrices(
    const std::vector<NativePoseBone>& raw_bones,
    const std::map<int, Vec3>& rotations
) {
    std::map<int, NativePoseBone> bones;
    for (std::size_t ordinal = 0; ordinal < raw_bones.size(); ++ordinal) {
        NativePoseBone bone = raw_bones[ordinal];
        if (bone.index < 0) {
            bone.index = static_cast<int>(ordinal);
        }
        bones[bone.index] = bone;
    }
    std::map<int, PoseMatrix4> bind_globals;
    std::map<int, PoseMatrix4> pose_globals;
    std::map<int, PoseMatrix4> skinning;
    const PoseMatrix4 identity = pose_identity_matrix();

    std::function<void(int, std::set<int>)> build = [&](int index, std::set<int> seen) {
        if (skinning.find(index) != skinning.end()) {
            return;
        }
        const auto bone_found = bones.find(index);
        if (bone_found == bones.end()) {
            return;
        }
        if (seen.find(index) != seen.end()) {
            bind_globals[index] = identity;
            pose_globals[index] = identity;
            skinning[index] = identity;
            return;
        }
        seen.insert(index);
        const NativePoseBone& bone = bone_found->second;
        int parent_index = bone.parent_index;
        if (parent_index == index || bones.find(parent_index) == bones.end()) {
            parent_index = -1;
        }
        if (parent_index >= 0) {
            build(parent_index, seen);
        }
        const PoseMatrix4 bind_global = bone.has_bind_matrix
            ? bone.bind_matrix
            : pose_translation_matrix(bone.position);
        bind_globals[index] = bind_global;
        PoseMatrix4 local_bind = bind_global;
        PoseMatrix4 parent_pose = identity;
        if (parent_index >= 0) {
            const PoseMatrix4 parent_bind_inverse = pose_invert_rigid_affine(bind_globals[parent_index]);
            local_bind = pose_matrix_multiply(parent_bind_inverse, bind_global);
            parent_pose = pose_globals[parent_index];
        }
        Vec3 rotation{0.0, 0.0, 0.0};
        const auto rotation_found = rotations.find(index);
        if (rotation_found != rotations.end()) {
            rotation = rotation_found->second;
        }
        const PoseMatrix4 pose_local = pose_matrix_multiply(local_bind, pose_euler_rotation_matrix(rotation));
        const PoseMatrix4 pose_global = pose_matrix_multiply(parent_pose, pose_local);
        pose_globals[index] = pose_global;
        const PoseMatrix4 inv_bind = bone.has_inv_bind_matrix ? bone.inv_bind_matrix : pose_invert_rigid_affine(bind_global);
        skinning[index] = pose_matrix_multiply(pose_global, inv_bind);
    };

    for (const auto& item : bones) {
        build(item.first, {});
    }
    return skinning;
}

Vec3 pose_skin_vertex(
    const Vec3& vertex,
    const std::vector<int>& bone_indices,
    const std::vector<double>& bone_weights,
    const std::map<int, PoseMatrix4>& skinning_matrices
) {
    if (bone_indices.size() != bone_weights.size()) {
        return vertex;
    }
    double total = 0.0;
    Vec3 result{0.0, 0.0, 0.0};
    for (std::size_t index = 0; index < bone_indices.size(); ++index) {
        const int bone_index = bone_indices[index];
        const double weight = bone_weights[index];
        if (bone_index < 0 || !std::isfinite(weight) || weight <= 0.0) {
            continue;
        }
        const auto matrix_found = skinning_matrices.find(bone_index);
        if (matrix_found == skinning_matrices.end()) {
            continue;
        }
        const Vec3 posed = pose_transform_point(matrix_found->second, vertex);
        result[0] += posed[0] * weight;
        result[1] += posed[1] * weight;
        result[2] += posed[2] * weight;
        total += weight;
    }
    if (total <= 1e-8) {
        return vertex;
    }
    return {result[0] / total, result[1] / total, result[2] / total};
}

std::vector<SubmeshPosePreviewResult> run_pose_preview(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::vector<NativePoseBone> bones = pose_bones_from_json(root.get("bones"));
    const std::map<int, Vec3> rotations = pose_rotations_from_json(root.get("rotations"));
    if (bones.empty() || rotations.empty()) {
        return {};
    }
    const std::map<int, PoseMatrix4> skinning = pose_skinning_matrices(bones, rotations);
    if (skinning.empty()) {
        return {};
    }

    std::vector<SubmeshPosePreviewResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshPosePreviewResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        if (result.index < 0) {
            continue;
        }
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        result.vertex_count = static_cast<int>(vertices.size());
        if (result.vertex_count <= 0) {
            continue;
        }
        const BoneAssignments assignments = mesh_bones_from_item(item);
        if (!valid_bone_assignments(assignments)
            || assignments.indices.size() != vertices.size()
            || assignments.weights.size() != vertices.size()) {
            continue;
        }
        result.vertices.reserve(vertices.size());
        for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
            const Vec3 posed = pose_skin_vertex(
                vertices[vertex_index],
                assignments.indices[vertex_index],
                assignments.weights[vertex_index],
                skinning
            );
            result.vertices.push_back(posed);
            if (std::fabs(posed[0] - vertices[vertex_index][0]) > 1e-6
                || std::fabs(posed[1] - vertices[vertex_index][1]) > 1e-6
                || std::fabs(posed[2] - vertices[vertex_index][2]) > 1e-6) {
                result.changed_vertices.push_back(static_cast<int>(vertex_index));
            }
        }
        if (!result.changed_vertices.empty()) {
            results.push_back(std::move(result));
        }
    }
    return results;
}

std::vector<SubmeshSkinWeightsResult> run_skin_weights(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string operation = string_or(root.get("operation"), "normalize");
    const int bone_index = int_or(root.get("bone_index"), -1);
    const double delta = number_or(root.get("delta"), 0.0);
    if (operation == "adjust" && (bone_index < 0 || !std::isfinite(delta))) {
        throw std::runtime_error("invalid skin weight adjust parameters");
    }
    if (operation != "adjust" && operation != "normalize" && operation != "transfer") {
        throw std::runtime_error("unsupported skin weight operation");
    }
    std::vector<SubmeshSkinWeightsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshSkinWeightsResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        if (result.index < 0) {
            continue;
        }
        result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.vertex_count = static_cast<int>(mesh_vertex_count_from_item(item));
        if (result.vertex_count <= 0) {
            continue;
        }
        BoneAssignments bones = mesh_bones_from_item(item);
        if (!valid_bone_assignments(bones) || bones.indices.size() != static_cast<std::size_t>(result.vertex_count)) {
            bones.indices.assign(static_cast<std::size_t>(result.vertex_count), {});
            bones.weights.assign(static_cast<std::size_t>(result.vertex_count), {});
        }
        std::set<int> selected_set = selected_vertices_from_binary_or_json(item, static_cast<std::size_t>(result.vertex_count));
        std::vector<int> selected_vertices(selected_set.begin(), selected_set.end());
        const std::vector<Vec3> target_vertices = operation == "transfer" ? mesh_vertices_from_item(item) : std::vector<Vec3>();
        const std::vector<Vec3> source_vertices = operation == "transfer"
            ? vertices_from_binary_or_json(item, "source_vertices_binary", "source_vertices")
            : std::vector<Vec3>();
        BoneAssignments source_bones = operation == "transfer" ? source_bone_assignments_from_item(item) : BoneAssignments();
        if (operation == "transfer" && (!valid_bone_assignments(source_bones) || source_bones.indices.size() != source_vertices.size())) {
            continue;
        }
        const std::vector<int> source_vertex_map = operation == "transfer"
            ? optional_source_vertex_map_from_item(item, static_cast<std::size_t>(result.vertex_count))
            : std::vector<int>();
        const bool remap_enabled = operation == "transfer" && bool_or(item.get("bone_remap_enabled"), false);
        const std::map<int, int> bone_remap = operation == "transfer" ? bone_remap_from_item(item) : std::map<int, int>();
        for (const int vertex_index : selected_vertices) {
            if (vertex_index < 0 || vertex_index >= result.vertex_count) {
                continue;
            }
            const std::size_t row = static_cast<std::size_t>(vertex_index);
            std::vector<int> next_indices;
            std::vector<double> next_weights;
            if (operation == "adjust") {
                nudge_bone_weight_native(bones.indices[row], bones.weights[row], bone_index, delta, next_indices, next_weights);
            } else if (operation == "normalize") {
                normalize_weight_row_native(bones.indices[row], bones.weights[row], next_indices, next_weights);
            } else {
                int source_index = -1;
                if (source_vertex_map.size() == static_cast<std::size_t>(result.vertex_count)) {
                    const int mapped = source_vertex_map[row];
                    if (mapped >= 0 && static_cast<std::size_t>(mapped) < source_vertices.size()) {
                        source_index = mapped;
                    }
                }
                if (source_index < 0
                    && target_vertices.size() == static_cast<std::size_t>(result.vertex_count)
                    && !source_vertices.empty()) {
                    source_index = nearest_source_vertex_index_native(target_vertices[row], source_vertices);
                }
                if (source_index < 0 || static_cast<std::size_t>(source_index) >= source_bones.indices.size()) {
                    continue;
                }
                transfer_weight_row_native(
                    source_bones.indices[static_cast<std::size_t>(source_index)],
                    source_bones.weights[static_cast<std::size_t>(source_index)],
                    remap_enabled,
                    bone_remap,
                    next_indices,
                    next_weights
                );
            }
            if (next_indices == bones.indices[row] && next_weights == bones.weights[row]) {
                continue;
            }
            bones.indices[row] = std::move(next_indices);
            bones.weights[row] = std::move(next_weights);
            result.changed_vertices.push_back(vertex_index);
        }
        if (result.changed_vertices.empty()) {
            continue;
        }
        result.bones = std::move(bones);
        if (MeshSessionSubmesh* session = mutable_mesh_session_submesh_for_item(item)) {
            session->bone_indices = result.bones.indices;
            session->bone_weights = result.bones.weights;
        }
        const std::vector<int> counts = bone_assignment_counts(result.bones);
        const std::vector<int> flat_indices = flatten_bone_indices(result.bones);
        const std::vector<double> flat_weights = flatten_bone_weights(result.bones);
        if (counts.size() != result.bones.indices.size() || flat_indices.size() != flat_weights.size()) {
            throw std::runtime_error("invalid skin weight output");
        }
        write_int_binary_file(result.bone_counts_path, counts);
        write_int_binary_file(result.bone_indices_path, flat_indices);
        write_double_binary_file(result.bone_weights_path, flat_weights);
        results.push_back(std::move(result));
    }
    return results;
}

ObjRoundtripManifestSubmesh obj_manifest_submesh_from_item(
    const JsonValue& item,
    int fallback_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces
) {
    const int index = int_or(item.get("index"), fallback_index);
    ObjRoundtripManifestSubmesh result;
    result.index = index;
    result.name = string_or(item.get("name"), std::string("part_") + std::to_string(index));
    result.material = string_or(item.get("material"), result.name);
    result.texture = string_or(item.get("texture"), "");
    result.vertex_count = static_cast<int>(vertices.size());
    result.face_count = static_cast<int>(faces.size());
    result.source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
    return result;
}

void write_obj_roundtrip_manifest(
    const std::string& manifest_path,
    const std::string& source_path,
    const std::string& source_format,
    const std::string& export_path,
    const std::string& companion_path,
    const std::vector<ObjRoundtripManifestSubmesh>& submeshes,
    const JsonValue* extra_payload
);

ObjExportResult run_obj_export(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("missing output_path");
    }
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const std::string base_name = string_or(root.get("base_name"), "mesh");
    const std::string source_path = string_or(root.get("source_path"), "");
    const std::string source_format = string_or(root.get("source_format"), "");
    const std::string mtl_filename = string_or(root.get("mtl_filename"), "");
    const double scale = number_or(root.get("scale"), 1.0);
    if (!std::isfinite(scale)) {
        throw std::runtime_error("non-finite OBJ export scale");
    }

    std::ofstream out(output_path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("cannot open OBJ output file: " + output_path);
    }

    int total_vertices = int_or(root.get("total_vertices"), 0);
    int total_faces = int_or(root.get("total_faces"), 0);
    if (total_vertices < 0) {
        total_vertices = 0;
    }
    if (total_faces < 0) {
        total_faces = 0;
    }

    out << "# Crimson Desert Mesh - " << base_name << "\n"
        << "# " << submeshes->array_value.size() << " submesh(es), "
        << total_vertices << " verts, " << total_faces << " faces\n"
        << "# Exported by Crimson Desert Mod Workbench\n"
        << "# source_path: " << source_path << "\n"
        << "# source_format: " << source_format << "\n";
    if (!mtl_filename.empty()) {
        out << "mtllib " << mtl_filename << "\n";
    }
    out << "\n";

    int vertex_offset = 1;
    int uv_offset = 1;
    int normal_offset = 1;
    ObjExportResult result;
    result.output_path = output_path;
    result.manifest_path = string_or(root.get("manifest_output_path"), "");
    std::vector<ObjRoundtripManifestSubmesh> manifest_submeshes;

    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), result.submesh_count);
        const std::string name = string_or(item.get("name"), std::string("part_") + std::to_string(index));
        const std::string material = string_or(item.get("material"), name);
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        manifest_submeshes.push_back(obj_manifest_submesh_from_item(item, index, vertices, faces));

        out << "o " << name << "\n";
        out << "usemtl " << material << "\n";
        out << std::fixed << std::setprecision(6);
        for (const Vec3& vertex : vertices) {
            out << "v " << vertex[0] * scale << ' ' << vertex[1] * scale << ' ' << vertex[2] * scale << "\n";
        }
        for (const Vec2& uv : uvs) {
            out << "vt " << uv[0] << ' ' << (1.0 - uv[1]) << "\n";
        }
        out << std::fixed << std::setprecision(4);
        for (const Vec3& normal : normals) {
            out << "vn " << normal[0] << ' ' << normal[1] << ' ' << normal[2] << "\n";
        }
        out << "s 1\n";

        const bool has_uv = !uvs.empty();
        const bool has_normals = !normals.empty();
        for (const std::array<int, 3>& face : faces) {
            const int va = face[0] + vertex_offset;
            const int vb = face[1] + vertex_offset;
            const int vc = face[2] + vertex_offset;
            if (has_uv && has_normals) {
                const int ta = face[0] + uv_offset;
                const int tb = face[1] + uv_offset;
                const int tc = face[2] + uv_offset;
                const int na = face[0] + normal_offset;
                const int nb = face[1] + normal_offset;
                const int nc = face[2] + normal_offset;
                out << "f " << va << '/' << ta << '/' << na << ' '
                    << vb << '/' << tb << '/' << nb << ' '
                    << vc << '/' << tc << '/' << nc << "\n";
            } else if (has_uv) {
                const int ta = face[0] + uv_offset;
                const int tb = face[1] + uv_offset;
                const int tc = face[2] + uv_offset;
                out << "f " << va << '/' << ta << ' ' << vb << '/' << tb << ' ' << vc << '/' << tc << "\n";
            } else if (has_normals) {
                const int na = face[0] + normal_offset;
                const int nb = face[1] + normal_offset;
                const int nc = face[2] + normal_offset;
                out << "f " << va << "//" << na << ' ' << vb << "//" << nb << ' ' << vc << "//" << nc << "\n";
            } else {
                out << "f " << va << ' ' << vb << ' ' << vc << "\n";
            }
        }
        out << "\n";
        vertex_offset += static_cast<int>(vertices.size());
        uv_offset += static_cast<int>(uvs.size());
        normal_offset += static_cast<int>(normals.size());
        result.vertex_count += static_cast<int>(vertices.size());
        result.face_count += static_cast<int>(faces.size());
        ++result.submesh_count;
    }

    if (!out) {
        throw std::runtime_error("cannot write OBJ output file: " + output_path);
    }
    if (!result.manifest_path.empty()) {
        write_obj_roundtrip_manifest(
            result.manifest_path,
            source_path,
            source_format,
            output_path,
            mtl_filename,
            manifest_submeshes,
            root.get("extra_payload")
        );
    }
    return result;
}

ObjManifestResult run_obj_manifest(const JsonValue& root) {
    const std::string manifest_path = string_or(root.get("manifest_output_path"), "");
    if (manifest_path.empty()) {
        throw std::runtime_error("missing manifest_output_path");
    }
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<ObjRoundtripManifestSubmesh> manifest_submeshes;
    ObjManifestResult result;
    result.manifest_path = manifest_path;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), static_cast<int>(manifest_submeshes.size()));
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        manifest_submeshes.push_back(obj_manifest_submesh_from_item(item, index, vertices, faces));
        result.vertex_count += static_cast<int>(vertices.size());
        result.face_count += static_cast<int>(faces.size());
        ++result.submesh_count;
    }
    write_obj_roundtrip_manifest(
        manifest_path,
        string_or(root.get("source_path"), ""),
        string_or(root.get("source_format"), ""),
        string_or(root.get("export_path"), ""),
        string_or(root.get("companion_path"), string_or(root.get("companion_filename"), "")),
        manifest_submeshes,
        root.get("extra_payload")
    );
    return result;
}

std::vector<double> flatten_fbx_vertices(const std::vector<Vec3>& vertices, double scale) {
    std::vector<double> result;
    result.reserve(vertices.size() * 3);
    for (const Vec3& vertex : vertices) {
        result.push_back(vertex[0] * scale);
        result.push_back(vertex[1] * scale);
        result.push_back(vertex[2] * scale);
    }
    return result;
}

std::vector<int> flatten_fbx_polygon_indices(const std::vector<std::array<int, 3>>& faces) {
    std::vector<int> result;
    result.reserve(faces.size() * 3);
    for (const std::array<int, 3>& face : faces) {
        result.push_back(face[0]);
        result.push_back(face[1]);
        result.push_back(face[2] ^ -1);
    }
    return result;
}

std::vector<double> flatten_fbx_normals(const std::vector<Vec3>& normals) {
    std::vector<double> result;
    result.reserve(normals.size() * 3);
    for (const Vec3& normal : normals) {
        result.push_back(normal[0]);
        result.push_back(normal[1]);
        result.push_back(normal[2]);
    }
    return result;
}

std::vector<double> flatten_fbx_uvs(const std::vector<Vec2>& uvs) {
    std::vector<double> result;
    result.reserve(uvs.size() * 2);
    for (const Vec2& uv : uvs) {
        result.push_back(uv[0]);
        result.push_back(1.0 - uv[1]);
    }
    return result;
}

std::vector<FbxGeometrySubmeshResult> run_fbx_geometry(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const double scale = number_or(root.get("scale"), 1.0);
    if (!std::isfinite(scale)) {
        throw std::runtime_error("non-finite FBX geometry scale");
    }
    const bool require_vertex_aligned_uvs = bool_or(root.get("require_vertex_aligned_uvs"), false);
    std::vector<FbxGeometrySubmeshResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        FbxGeometrySubmeshResult result;
        result.index = int_or(item.get("index"), static_cast<int>(results.size()));
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.indices_path = string_or(item.get("indices_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        if (result.vertices_path.empty() || result.indices_path.empty() || result.normals_path.empty() || result.uvs_path.empty()) {
            throw std::runtime_error("missing FBX geometry output path");
        }

        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (require_vertex_aligned_uvs && uvs.size() != vertices.size()) {
            uvs.clear();
        }

        const std::vector<double> flat_vertices = flatten_fbx_vertices(vertices, scale);
        const std::vector<int> flat_indices = flatten_fbx_polygon_indices(faces);
        const std::vector<double> flat_normals = flatten_fbx_normals(normals);
        const std::vector<double> flat_uvs = flatten_fbx_uvs(uvs);

        write_double_binary_file(result.vertices_path, flat_vertices);
        write_int_binary_file(result.indices_path, flat_indices);
        write_double_binary_file(result.normals_path, flat_normals);
        write_double_binary_file(result.uvs_path, flat_uvs);

        result.vertex_count = static_cast<int>(vertices.size());
        result.face_count = static_cast<int>(faces.size());
        result.normal_count = static_cast<int>(normals.size());
        result.uv_count = static_cast<int>(uvs.size());
        result.vertex_value_count = flat_vertices.size();
        result.index_value_count = flat_indices.size();
        result.normal_value_count = flat_normals.size();
        result.uv_value_count = flat_uvs.size();
        results.push_back(std::move(result));
    }
    return results;
}

struct NativeFbxProperty {
    enum class Kind { Int32, Int64, Double, String, DoubleArray, IntArray };

    Kind kind = Kind::Int32;
    int int_value = 0;
    long long long_value = 0;
    double double_value = 0.0;
    std::string string_value;
    std::vector<double> double_values;
    std::vector<int> int_values;
};

NativeFbxProperty fbx_i32(int value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Int32;
    prop.int_value = value;
    return prop;
}

NativeFbxProperty fbx_i64(long long value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Int64;
    prop.long_value = value;
    return prop;
}

NativeFbxProperty fbx_f64(double value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::Double;
    prop.double_value = value;
    return prop;
}

NativeFbxProperty fbx_string(std::string value) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::String;
    prop.string_value = std::move(value);
    return prop;
}

NativeFbxProperty fbx_f64_array(std::vector<double> values) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::DoubleArray;
    prop.double_values = std::move(values);
    return prop;
}

NativeFbxProperty fbx_i32_array(std::vector<int> values) {
    NativeFbxProperty prop;
    prop.kind = NativeFbxProperty::Kind::IntArray;
    prop.int_values = std::move(values);
    return prop;
}

void fbx_append_u8(std::vector<char>& out, unsigned int value) {
    out.push_back(static_cast<char>(value & 0xffU));
}

void fbx_append_u32(std::vector<char>& out, std::uint32_t value) {
    for (int shift = 0; shift < 32; shift += 8) {
        out.push_back(static_cast<char>((value >> shift) & 0xffU));
    }
}

void fbx_patch_u32(std::vector<char>& out, std::size_t offset, std::uint32_t value) {
    if (offset + 4 > out.size()) {
        throw std::runtime_error("invalid FBX patch offset");
    }
    for (int shift = 0; shift < 32; shift += 8) {
        out[offset + static_cast<std::size_t>(shift / 8)] = static_cast<char>((value >> shift) & 0xffU);
    }
}

void fbx_append_i32(std::vector<char>& out, int value) {
    fbx_append_u32(out, static_cast<std::uint32_t>(static_cast<std::int32_t>(value)));
}

void fbx_append_i64(std::vector<char>& out, long long value) {
    const std::uint64_t raw = static_cast<std::uint64_t>(static_cast<std::int64_t>(value));
    for (int shift = 0; shift < 64; shift += 8) {
        out.push_back(static_cast<char>((raw >> shift) & 0xffULL));
    }
}

void fbx_append_double(std::vector<char>& out, double value) {
    std::uint64_t raw = 0;
    std::memcpy(&raw, &value, sizeof(raw));
    for (int shift = 0; shift < 64; shift += 8) {
        out.push_back(static_cast<char>((raw >> shift) & 0xffULL));
    }
}

void fbx_append_bytes(std::vector<char>& out, const char* data, std::size_t size) {
    out.insert(out.end(), data, data + size);
}

void fbx_append_string_bytes(std::vector<char>& out, const std::string& value) {
    if (value.size() > static_cast<std::size_t>(UINT_MAX)) {
        throw std::runtime_error("FBX string too large");
    }
    fbx_append_u32(out, static_cast<std::uint32_t>(value.size()));
    fbx_append_bytes(out, value.data(), value.size());
}

void fbx_append_property(std::vector<char>& out, const NativeFbxProperty& prop) {
    switch (prop.kind) {
    case NativeFbxProperty::Kind::Int32:
        fbx_append_u8(out, 'I');
        fbx_append_i32(out, prop.int_value);
        break;
    case NativeFbxProperty::Kind::Int64:
        fbx_append_u8(out, 'L');
        fbx_append_i64(out, prop.long_value);
        break;
    case NativeFbxProperty::Kind::Double:
        fbx_append_u8(out, 'D');
        fbx_append_double(out, prop.double_value);
        break;
    case NativeFbxProperty::Kind::String:
        fbx_append_u8(out, 'S');
        fbx_append_string_bytes(out, prop.string_value);
        break;
    case NativeFbxProperty::Kind::DoubleArray: {
        const std::size_t raw_size = prop.double_values.size() * sizeof(double);
        if (prop.double_values.size() > static_cast<std::size_t>(UINT_MAX) || raw_size > static_cast<std::size_t>(UINT_MAX)) {
            throw std::runtime_error("FBX double array too large");
        }
        fbx_append_u8(out, 'd');
        fbx_append_u32(out, static_cast<std::uint32_t>(prop.double_values.size()));
        fbx_append_u32(out, 0);
        fbx_append_u32(out, static_cast<std::uint32_t>(raw_size));
        for (const double value : prop.double_values) {
            fbx_append_double(out, value);
        }
        break;
    }
    case NativeFbxProperty::Kind::IntArray: {
        const std::size_t raw_size = prop.int_values.size() * sizeof(std::int32_t);
        if (prop.int_values.size() > static_cast<std::size_t>(UINT_MAX) || raw_size > static_cast<std::size_t>(UINT_MAX)) {
            throw std::runtime_error("FBX int array too large");
        }
        fbx_append_u8(out, 'i');
        fbx_append_u32(out, static_cast<std::uint32_t>(prop.int_values.size()));
        fbx_append_u32(out, 0);
        fbx_append_u32(out, static_cast<std::uint32_t>(raw_size));
        for (const int value : prop.int_values) {
            fbx_append_i32(out, value);
        }
        break;
    }
    }
}

using FbxChildWriter = std::function<void(std::vector<char>&)>;

void fbx_node(
    std::vector<char>& out,
    const std::string& name,
    const std::vector<NativeFbxProperty>& props = {},
    const std::vector<FbxChildWriter>& children = {}
) {
    if (name.size() > 255) {
        throw std::runtime_error("FBX node name too long");
    }
    std::vector<char> prop_bytes;
    for (const NativeFbxProperty& prop : props) {
        fbx_append_property(prop_bytes, prop);
    }
    if (out.size() > static_cast<std::size_t>(UINT_MAX) || prop_bytes.size() > static_cast<std::size_t>(UINT_MAX)) {
        throw std::runtime_error("FBX buffer too large");
    }
    const std::size_t end_offset_position = out.size();
    fbx_append_u32(out, 0);
    fbx_append_u32(out, static_cast<std::uint32_t>(props.size()));
    fbx_append_u32(out, static_cast<std::uint32_t>(prop_bytes.size()));
    fbx_append_u8(out, static_cast<unsigned int>(name.size()));
    fbx_append_bytes(out, name.data(), name.size());
    if (!prop_bytes.empty()) {
        fbx_append_bytes(out, prop_bytes.data(), prop_bytes.size());
    }
    for (const FbxChildWriter& child : children) {
        child(out);
    }
    if (!children.empty()) {
        out.insert(out.end(), 13, '\0');
    }
    if (out.size() > static_cast<std::size_t>(UINT_MAX)) {
        throw std::runtime_error("FBX file too large");
    }
    fbx_patch_u32(out, end_offset_position, static_cast<std::uint32_t>(out.size()));
}

std::string fbx_object_name(const std::string& name, const std::string& suffix) {
    std::string result = name;
    result.push_back('\0');
    result.push_back('\1');
    result += suffix;
    return result;
}

struct NativeFbxSubmesh {
    std::string name;
    std::string material;
    std::vector<double> vertices_flat;
    std::vector<int> indices_flat;
    std::vector<double> normals_flat;
    std::vector<double> uvs_flat;
    int vertex_count = 0;
    int face_count = 0;
};

struct NativeFbxBone {
    int index = -1;
    int parent_index = -1;
    std::string name;
    Vec3 position{0.0, 0.0, 0.0};
    double visual_size = 0.02;
};

std::vector<NativeFbxSubmesh> native_fbx_submeshes_from_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const double scale = number_or(root.get("scale"), 1.0);
    if (!std::isfinite(scale)) {
        throw std::runtime_error("non-finite FBX export scale");
    }

    std::vector<NativeFbxSubmesh> result;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), static_cast<int>(result.size()));
        NativeFbxSubmesh submesh;
        submesh.name = string_or(item.get("name"), std::string("part_") + std::to_string(index));
        if (submesh.name.empty()) {
            submesh.name = std::string("part_") + std::to_string(index);
        }
        submesh.material = string_or(item.get("material"), submesh.name);
        if (submesh.material.empty()) {
            submesh.material = submesh.name;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        submesh.vertices_flat = flatten_fbx_vertices(vertices, scale);
        submesh.indices_flat = flatten_fbx_polygon_indices(faces);
        submesh.normals_flat = flatten_fbx_normals(normals);
        submesh.uvs_flat = flatten_fbx_uvs(uvs);
        submesh.vertex_count = static_cast<int>(vertices.size());
        submesh.face_count = static_cast<int>(faces.size());
        result.push_back(std::move(submesh));
    }
    return result;
}

std::vector<NativeFbxBone> native_fbx_bones_from_json(const JsonValue& root) {
    const JsonValue* bones_value = root.get("bones");
    if (bones_value == nullptr || bones_value->type != JsonValue::Type::Array) {
        return {};
    }
    const double scale = number_or(root.get("scale"), 1.0);
    const double abs_scale = std::abs(scale) > 1e-8 ? std::abs(scale) : 1.0;
    std::vector<NativeFbxBone> bones;
    bones.reserve(bones_value->array_value.size());
    for (const JsonValue& item : bones_value->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        NativeFbxBone bone;
        bone.index = int_or(item.get("index"), static_cast<int>(bones.size()));
        bone.parent_index = int_or(item.get("parent_index"), -1);
        bone.name = string_or(item.get("name"), std::string("Bone_") + std::to_string(bone.index));
        if (bone.name.empty()) {
            bone.name = std::string("Bone_") + std::to_string(bone.index);
        }
        bone.position = vec3_or(item.get("position"), {0.0, 0.0, 0.0});
        bones.push_back(std::move(bone));
    }

    std::map<int, std::vector<NativeFbxBone*>> children_by_parent;
    std::map<int, NativeFbxBone*> bones_by_index;
    for (NativeFbxBone& bone : bones) {
        bones_by_index[bone.index] = &bone;
        if (bone.parent_index >= 0) {
            children_by_parent[bone.parent_index].push_back(&bone);
        }
    }

    const double default_leaf_size = 0.02 * abs_scale;
    for (NativeFbxBone& bone : bones) {
        double best_distance = 0.0;
        const auto found_children = children_by_parent.find(bone.index);
        if (found_children != children_by_parent.end()) {
            for (const NativeFbxBone* child : found_children->second) {
                const double distance = std::sqrt(distance_squared_vec3(child->position, bone.position));
                if (distance > best_distance) {
                    best_distance = distance;
                }
            }
        }
        if (best_distance > 1e-4) {
            bone.visual_size = best_distance * abs_scale;
        } else {
            const auto parent = bones_by_index.find(bone.parent_index);
            bone.visual_size = parent != bones_by_index.end() ? parent->second->visual_size * 0.5 : default_leaf_size;
        }
        bone.visual_size = std::max(0.005 * abs_scale, std::min(2.0 * abs_scale, bone.visual_size));
    }
    for (NativeFbxBone& bone : bones) {
        bone.position = {bone.position[0] * scale, bone.position[1] * scale, bone.position[2] * scale};
    }
    return bones;
}

FbxExportResult run_fbx_export(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("missing output_path");
    }
    std::vector<NativeFbxSubmesh> submeshes = native_fbx_submeshes_from_json(root);
    std::vector<NativeFbxBone> bones = native_fbx_bones_from_json(root);

    std::vector<long long> mesh_ids;
    std::vector<long long> model_ids;
    std::vector<long long> mat_ids;
    std::map<int, long long> bone_model_ids;
    std::map<int, long long> bone_attr_ids;
    mesh_ids.reserve(submeshes.size());
    model_ids.reserve(submeshes.size());
    mat_ids.reserve(submeshes.size());
    long long id_ctr = 3000000000LL;
    const auto uid = [&id_ctr]() -> long long {
        id_ctr += 1;
        return id_ctr;
    };
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        mesh_ids.push_back(uid());
        model_ids.push_back(uid());
        mat_ids.push_back(uid());
    }
    for (const NativeFbxBone& bone : bones) {
        bone_model_ids[bone.index] = uid();
        bone_attr_ids[bone.index] = uid();
    }
    (void)uid();

    std::vector<char> out;
    const char header[] = "Kaydara FBX Binary  ";
    fbx_append_bytes(out, header, sizeof(header));
    fbx_append_u8(out, 0x1a);
    fbx_append_u8(out, 0x00);
    fbx_append_u32(out, 7400);

    fbx_node(
        out,
        "FBXHeaderExtension",
        {},
        {
            [](std::vector<char>& node_out) { fbx_node(node_out, "FBXHeaderVersion", {fbx_i32(1003)}); },
            [](std::vector<char>& node_out) { fbx_node(node_out, "FBXVersion", {fbx_i32(7400)}); },
            [](std::vector<char>& node_out) { fbx_node(node_out, "Creator", {fbx_string("Crimson Desert Mod Workbench Mesh Exporter")}); },
        }
    );

    fbx_node(
        out,
        "GlobalSettings",
        {},
        {
            [](std::vector<char>& node_out) {
                fbx_node(
                    node_out,
                    "Properties70",
                    {},
                    {
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("UpAxis"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(1)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("UpAxisSign"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(1)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("FrontAxis"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(2)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("FrontAxisSign"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(1)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("CoordAxis"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(0)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("CoordAxisSign"), fbx_string("int"), fbx_string("Integer"), fbx_string(""), fbx_i32(1)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("UnitScaleFactor"), fbx_string("double"), fbx_string("Number"), fbx_string(""), fbx_f64(1.0)}); },
                    }
                );
            },
        }
    );

    fbx_node(
        out,
        "Objects",
        {},
        {
            [&submeshes, &bones, &mesh_ids, &model_ids, &mat_ids, &bone_model_ids, &bone_attr_ids](std::vector<char>& objects_out) {
                for (std::size_t index = 0; index < submeshes.size(); ++index) {
                    const NativeFbxSubmesh& submesh = submeshes[index];
                    fbx_node(
                        objects_out,
                        "Geometry",
                        {fbx_i64(mesh_ids[index]), fbx_string(fbx_object_name(submesh.name, "Geometry")), fbx_string("Mesh")},
                        {
                            [&submesh](std::vector<char>& geom_out) { fbx_node(geom_out, "Vertices", {fbx_f64_array(submesh.vertices_flat)}); },
                            [&submesh](std::vector<char>& geom_out) { fbx_node(geom_out, "PolygonVertexIndex", {fbx_i32_array(submesh.indices_flat)}); },
                            [&submesh](std::vector<char>& geom_out) {
                                if (!submesh.normals_flat.empty()) {
                                    fbx_node(
                                        geom_out,
                                        "LayerElementNormal",
                                        {fbx_i32(0)},
                                        {
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "Version", {fbx_i32(101)}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "Name", {fbx_string("")}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "MappingInformationType", {fbx_string("ByVertice")}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "ReferenceInformationType", {fbx_string("Direct")}); },
                                            [&submesh](std::vector<char>& layer_out) { fbx_node(layer_out, "Normals", {fbx_f64_array(submesh.normals_flat)}); },
                                        }
                                    );
                                }
                            },
                            [&submesh](std::vector<char>& geom_out) {
                                if (!submesh.uvs_flat.empty()) {
                                    fbx_node(
                                        geom_out,
                                        "LayerElementUV",
                                        {fbx_i32(0)},
                                        {
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "Version", {fbx_i32(101)}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "Name", {fbx_string("UVMap")}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "MappingInformationType", {fbx_string("ByVertice")}); },
                                            [](std::vector<char>& layer_out) { fbx_node(layer_out, "ReferenceInformationType", {fbx_string("Direct")}); },
                                            [&submesh](std::vector<char>& layer_out) { fbx_node(layer_out, "UV", {fbx_f64_array(submesh.uvs_flat)}); },
                                        }
                                    );
                                }
                            },
                            [&submesh](std::vector<char>& geom_out) {
                                fbx_node(
                                    geom_out,
                                    "Layer",
                                    {fbx_i32(0)},
                                    {
                                        [](std::vector<char>& layer_out) { fbx_node(layer_out, "Version", {fbx_i32(100)}); },
                                        [](std::vector<char>& layer_out) {
                                            fbx_node(
                                                layer_out,
                                                "LayerElement",
                                                {},
                                                {
                                                    [](std::vector<char>& le_out) { fbx_node(le_out, "Type", {fbx_string("LayerElementNormal")}); },
                                                    [](std::vector<char>& le_out) { fbx_node(le_out, "TypedIndex", {fbx_i32(0)}); },
                                                }
                                            );
                                        },
                                        [&submesh](std::vector<char>& layer_out) {
                                            if (!submesh.uvs_flat.empty()) {
                                                fbx_node(
                                                    layer_out,
                                                    "LayerElement",
                                                    {},
                                                    {
                                                        [](std::vector<char>& le_out) { fbx_node(le_out, "Type", {fbx_string("LayerElementUV")}); },
                                                        [](std::vector<char>& le_out) { fbx_node(le_out, "TypedIndex", {fbx_i32(0)}); },
                                                    }
                                                );
                                            }
                                        },
                                    }
                                );
                            },
                        }
                    );

                    fbx_node(
                        objects_out,
                        "Model",
                        {fbx_i64(model_ids[index]), fbx_string(fbx_object_name(submesh.name, "Model")), fbx_string("Mesh")},
                        {
                            [](std::vector<char>& model_out) { fbx_node(model_out, "Version", {fbx_i32(232)}); },
                            [](std::vector<char>& model_out) {
                                fbx_node(
                                    model_out,
                                    "Properties70",
                                    {},
                                    {
                                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("Lcl Translation"), fbx_string("Lcl Translation"), fbx_string(""), fbx_string("A"), fbx_f64(0.0), fbx_f64(0.0), fbx_f64(0.0)}); },
                                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("Lcl Rotation"), fbx_string("Lcl Rotation"), fbx_string(""), fbx_string("A"), fbx_f64(0.0), fbx_f64(0.0), fbx_f64(0.0)}); },
                                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("Lcl Scaling"), fbx_string("Lcl Scaling"), fbx_string(""), fbx_string("A"), fbx_f64(1.0), fbx_f64(1.0), fbx_f64(1.0)}); },
                                    }
                                );
                            },
                        }
                    );

                    fbx_node(
                        objects_out,
                        "Material",
                        {fbx_i64(mat_ids[index]), fbx_string(fbx_object_name(submesh.material, "Material")), fbx_string("")},
                        {
                            [](std::vector<char>& mat_out) { fbx_node(mat_out, "Version", {fbx_i32(102)}); },
                            [](std::vector<char>& mat_out) { fbx_node(mat_out, "ShadingModel", {fbx_string("phong")}); },
                            [](std::vector<char>& mat_out) {
                                fbx_node(
                                    mat_out,
                                    "Properties70",
                                    {},
                                    {
                                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("DiffuseColor"), fbx_string("Color"), fbx_string(""), fbx_string("A"), fbx_f64(0.8), fbx_f64(0.8), fbx_f64(0.8)}); },
                                    }
                                );
                            },
                        }
                    );
                }
                for (const NativeFbxBone& bone : bones) {
                    const auto attr_found = bone_attr_ids.find(bone.index);
                    const auto model_found = bone_model_ids.find(bone.index);
                    if (attr_found == bone_attr_ids.end() || model_found == bone_model_ids.end()) {
                        continue;
                    }
                    fbx_node(
                        objects_out,
                        "NodeAttribute",
                        {fbx_i64(attr_found->second), fbx_string(fbx_object_name(bone.name, "NodeAttribute")), fbx_string("LimbNode")},
                        {
                            [](std::vector<char>& attr_out) { fbx_node(attr_out, "TypeFlags", {fbx_string("Skeleton")}); },
                            [&bone](std::vector<char>& attr_out) {
                                fbx_node(
                                    attr_out,
                                    "Properties70",
                                    {},
                                    {
                                        [&bone](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("Size"), fbx_string("double"), fbx_string("Number"), fbx_string(""), fbx_f64(bone.visual_size)}); },
                                    }
                                );
                            },
                        }
                    );
                    fbx_node(
                        objects_out,
                        "Model",
                        {fbx_i64(model_found->second), fbx_string(fbx_object_name(bone.name, "Model")), fbx_string("LimbNode")},
                        {
                            [](std::vector<char>& bone_model_out) { fbx_node(bone_model_out, "Version", {fbx_i32(232)}); },
                            [&bone](std::vector<char>& bone_model_out) {
                                fbx_node(
                                    bone_model_out,
                                    "Properties70",
                                    {},
                                    {
                                        [&bone](std::vector<char>& props_out) {
                                            fbx_node(
                                                props_out,
                                                "P",
                                                {
                                                    fbx_string("Lcl Translation"),
                                                    fbx_string("Lcl Translation"),
                                                    fbx_string(""),
                                                    fbx_string("A"),
                                                    fbx_f64(bone.position[0]),
                                                    fbx_f64(bone.position[1]),
                                                    fbx_f64(bone.position[2]),
                                                }
                                            );
                                        },
                                    }
                                );
                            },
                        }
                    );
                }
            },
        }
    );

    fbx_node(
        out,
        "Connections",
        {},
        {
            [&submeshes, &bones, &mesh_ids, &model_ids, &mat_ids, &bone_model_ids, &bone_attr_ids](std::vector<char>& connections_out) {
                for (std::size_t index = 0; index < submeshes.size(); ++index) {
                    fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(model_ids[index]), fbx_i64(0)});
                    fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(mesh_ids[index]), fbx_i64(model_ids[index])});
                    fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(mat_ids[index]), fbx_i64(model_ids[index])});
                }
                for (const NativeFbxBone& bone : bones) {
                    const auto attr_found = bone_attr_ids.find(bone.index);
                    const auto model_found = bone_model_ids.find(bone.index);
                    if (attr_found == bone_attr_ids.end() || model_found == bone_model_ids.end()) {
                        continue;
                    }
                    fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(attr_found->second), fbx_i64(model_found->second)});
                    const auto parent_model = bone_model_ids.find(bone.parent_index);
                    fbx_node(
                        connections_out,
                        "C",
                        {
                            fbx_string("OO"),
                            fbx_i64(model_found->second),
                            fbx_i64(parent_model != bone_model_ids.end() ? parent_model->second : 0),
                        }
                    );
                }
            },
        }
    );

    out.insert(out.end(), 13, '\0');
    const unsigned char padding[] = {0xfa, 0xbc, 0xab, 0x09, 0xd0, 0xc8, 0xd4, 0x66, 0xb1, 0x76, 0xfb, 0x83, 0x1c, 0xf7, 0x26, 0x7e};
    for (const unsigned char value : padding) {
        fbx_append_u8(out, value);
    }
    out.insert(out.end(), 4, '\0');
    fbx_append_u32(out, 7400);
    out.insert(out.end(), 120, '\0');
    const unsigned char footer[] = {0xf8, 0x5a, 0x8c, 0x6a, 0xde, 0xf5, 0xd9, 0x7e, 0xec, 0xe9, 0x0c, 0xe3, 0x75, 0x8f, 0x29, 0x0b};
    for (const unsigned char value : footer) {
        fbx_append_u8(out, value);
    }

    write_binary_file(output_path, out, false);

    FbxExportResult result;
    result.output_path = output_path;
    result.submesh_count = static_cast<int>(submeshes.size());
    for (const NativeFbxSubmesh& submesh : submeshes) {
        result.vertex_count += submesh.vertex_count;
        result.face_count += submesh.face_count;
    }
    return result;
}

void write_escaped(std::ostream& out, const std::string& text) {
    out << '"';
    for (const char ch : text) {
        switch (ch) {
        case '"':
            out << "\\\"";
            break;
        case '\\':
            out << "\\\\";
            break;
        case '\n':
            out << "\\n";
            break;
        case '\r':
            out << "\\r";
            break;
        case '\t':
            out << "\\t";
            break;
        default:
            out << ch;
            break;
        }
    }
    out << '"';
}

void write_vec3(std::ostream& out, const Vec3& value) {
    out << '[' << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2] << ']';
}

void write_vec2(std::ostream& out, const Vec2& value) {
    out << '[' << std::setprecision(17) << value[0] << ',' << value[1] << ']';
}

void write_int_vector(std::ostream& out, const std::vector<int>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        out << values[index];
    }
    out << ']';
}

void write_json_value(std::ostream& out, const JsonValue& value) {
    switch (value.type) {
    case JsonValue::Type::Null:
        out << "null";
        break;
    case JsonValue::Type::Bool:
        out << (value.bool_value ? "true" : "false");
        break;
    case JsonValue::Type::Number:
        if (std::isfinite(value.number_value)) {
            out << std::setprecision(17) << value.number_value;
        } else {
            out << "null";
        }
        break;
    case JsonValue::Type::String:
        write_escaped(out, value.string_value);
        break;
    case JsonValue::Type::Array:
        out << '[';
        for (std::size_t index = 0; index < value.array_value.size(); ++index) {
            if (index > 0) {
                out << ',';
            }
            write_json_value(out, value.array_value[index]);
        }
        out << ']';
        break;
    case JsonValue::Type::Object:
        out << '{';
        for (auto iter = value.object_value.begin(); iter != value.object_value.end(); ++iter) {
            if (iter != value.object_value.begin()) {
                out << ',';
            }
            write_escaped(out, iter->first);
            out << ':';
            write_json_value(out, iter->second);
        }
        out << '}';
        break;
    }
}

void write_obj_roundtrip_manifest(
    const std::string& manifest_path,
    const std::string& source_path,
    const std::string& source_format,
    const std::string& export_path,
    const std::string& companion_path,
    const std::vector<ObjRoundtripManifestSubmesh>& submeshes,
    const JsonValue* extra_payload
) {
    std::ofstream out(manifest_path, std::ios::binary | std::ios::trunc);
    if (!out) {
        throw std::runtime_error("cannot open OBJ round-trip manifest: " + manifest_path);
    }
    std::set<std::string> emitted;
    bool first = true;
    auto field = [&](const std::string& key) {
        if (!first) {
            out << ',';
        }
        first = false;
        emitted.insert(key);
        write_escaped(out, key);
        out << ':';
    };
    auto string_field = [&](const std::string& key, const std::string& value) {
        field(key);
        write_escaped(out, value);
    };

    out << "{\n";
    string_field("format", "mesh_roundtrip_manifest_v2");
    string_field("source_path", source_path);
    string_field("source_format", source_format);
    string_field("export_path", filename_from_path(export_path));
    string_field("companion_filename", filename_from_path(companion_path));
    string_field("exported_utc", utc_timestamp_seconds());
    field("roundtrip_policy");
    out << "{\"primary_workflow\":\"obj_first\",\"default_import_policy\":\"auto-fix safe, warn risky\"}";
    field("submeshes");
    out << '[';
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        const ObjRoundtripManifestSubmesh& submesh = submeshes[index];
        out << "{\"index\":" << submesh.index
            << ",\"name\":";
        write_escaped(out, submesh.name);
        out << ",\"material\":";
        write_escaped(out, submesh.material);
        out << ",\"texture\":";
        write_escaped(out, submesh.texture);
        out << ",\"vertex_count\":" << submesh.vertex_count
            << ",\"face_count\":" << submesh.face_count
            << ",\"source_vertex_map\":";
        write_int_vector(out, submesh.source_vertex_map);
        out << '}';
    }
    out << ']';
    if (extra_payload != nullptr && extra_payload->type == JsonValue::Type::Object) {
        for (const auto& entry : extra_payload->object_value) {
            if (emitted.find(entry.first) != emitted.end()) {
                continue;
            }
            field(entry.first);
            write_json_value(out, entry.second);
        }
    }
    out << "\n}";
    if (!out) {
        throw std::runtime_error("cannot write OBJ round-trip manifest: " + manifest_path);
    }
}

void write_vec3_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":3,\"type\":\"f64\",\"finite_checked\":true}";
}

void write_vec2_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":2,\"type\":\"f64\",\"finite_checked\":true}";
}

void write_f64_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":1,\"type\":\"f64\"}";
}

void write_int_binary_descriptor(std::ostream& out, const std::string& path, std::size_t count, int components) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count << ",\"components\":" << components << ",\"type\":\"i32\"}";
}

std::string static_donor_indices_report_json(const std::vector<SubmeshStaticDonorIndicesResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"static_donor_indices\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshStaticDonorIndicesResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"original_vertex_count\":" << result.original_vertex_count
            << ",\"new_vertex_count\":" << result.new_vertex_count
            << ",\"sequence_alignment_used\":" << (result.sequence_alignment_used ? "true" : "false")
            << ",\"sequence_alignment_fallback\":" << (result.sequence_alignment_fallback ? "true" : "false")
            << ",\"donor_indices_binary\":";
        write_int_binary_descriptor(out, result.donor_indices_path, result.donor_indices.size(), 1);
        out << '}';
    }
    out << "]}";
    return out.str();
}

void write_changed_vertices_report(
    std::ostream& out,
    const std::vector<int>& changed_vertices,
    const std::string& changed_vertices_path,
    int& changed_vertex_start
);

std::string pose_preview_report_json(const std::vector<SubmeshPosePreviewResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"pose_preview\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshPosePreviewResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"changed_count\":" << result.changed_vertices.size();
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << ",\"vertices_binary\":";
        write_vec3_binary_file(result.vertices_path, result.vertices);
        write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string skin_weights_report_json(const std::vector<SubmeshSkinWeightsResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"skin_weights\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const SubmeshSkinWeightsResult& result = results[index];
        const std::vector<int> counts = bone_assignment_counts(result.bones);
        const std::vector<int> flat_indices = flatten_bone_indices(result.bones);
        const std::vector<double> flat_weights = flatten_bone_weights(result.bones);
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"changed_count\":" << result.changed_vertices.size();
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << ",\"bone_counts_binary\":";
        write_int_binary_descriptor(out, result.bone_counts_path, counts.size(), 1);
        out << ",\"bone_indices_binary\":";
        write_int_binary_descriptor(out, result.bone_indices_path, flat_indices.size(), 1);
        out << ",\"bone_weights_binary\":";
        write_f64_binary_descriptor(out, result.bone_weights_path, flat_weights.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string obj_export_report_json(const ObjExportResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"obj_export\",\"output_path\":";
    write_escaped(out, result.output_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count;
    if (!result.manifest_path.empty()) {
        out << ",\"manifest_path\":";
        write_escaped(out, result.manifest_path);
    }
    out << "}";
    return out.str();
}

std::string obj_manifest_report_json(const ObjManifestResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"obj_manifest\",\"manifest_path\":";
    write_escaped(out, result.manifest_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count
        << "}";
    return out.str();
}

std::string fbx_geometry_report_json(const std::vector<FbxGeometrySubmeshResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"fbx_geometry\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index) {
            out << ',';
        }
        const FbxGeometrySubmeshResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"face_count\":" << result.face_count
            << ",\"normal_count\":" << result.normal_count
            << ",\"uv_count\":" << result.uv_count
            << ",\"vertices_binary\":";
        write_f64_binary_descriptor(out, result.vertices_path, result.vertex_value_count);
        out << ",\"indices_binary\":";
        write_int_binary_descriptor(out, result.indices_path, result.index_value_count, 1);
        out << ",\"normals_binary\":";
        write_f64_binary_descriptor(out, result.normals_path, result.normal_value_count);
        out << ",\"uvs_binary\":";
        write_f64_binary_descriptor(out, result.uvs_path, result.uv_value_count);
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string fbx_export_report_json(const FbxExportResult& result) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"fbx_export\",\"output_path\":";
    write_escaped(out, result.output_path);
    out << ",\"submesh_count\":" << result.submesh_count
        << ",\"vertex_count\":" << result.vertex_count
        << ",\"face_count\":" << result.face_count
        << "}";
    return out.str();
}

void write_preview_binary_descriptor(
    std::ostream& out,
    const std::string& path,
    std::size_t count,
    int components,
    const std::string& type
) {
    out << "{\"path\":";
    write_escaped(out, path);
    out << ",\"count\":" << count
        << ",\"components\":" << components
        << ",\"type\":";
    write_escaped(out, type);
    out << ",\"delete_after\":true}";
}

std::string sibling_binary_path(const std::string& path, const std::string& suffix) {
    return path.empty() ? std::string() : path + suffix;
}

std::string morph_apply_report_json(const std::vector<SubmeshMorphApplyResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_apply\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphApplyResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"normal_count\":" << result.normal_count
            << ",\"vertices_binary\":";
        write_escaped(out, result.vertices_path);
        out << ",\"normals_binary\":";
        write_escaped(out, result.normals_path);
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string morph_post_edit_delta_report_json(const std::vector<SubmeshMorphPostEditDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_post_edit_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphPostEditDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"zero_delta\":" << (result.zero_delta ? "true" : "false")
            << ",\"deltas_binary\":";
        if (result.zero_delta) {
            out << "null";
        } else {
            write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string morph_target_delta_report_json(const std::vector<SubmeshMorphPostEditDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"morph_target_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMorphPostEditDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"deltas_binary\":";
        write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string region_volume_delta_report_json(const std::vector<SubmeshRegionVolumeDeltaResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"region_volume_delta\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshRegionVolumeDeltaResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"selected_vertex_count\":" << result.selected_vertex_count
            << ",\"weighted_vertex_count\":" << result.weighted_vertex_count
            << ",\"deltas_binary\":";
        write_vec3_binary_descriptor(out, result.deltas_path, result.deltas.size());
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::vector<int> valid_vertex_indices(const std::vector<int>& indices, std::size_t vertex_count) {
    std::vector<int> result;
    result.reserve(indices.size());
    for (const int index : indices) {
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
            result.push_back(index);
        }
    }
    return result;
}

void write_flat_vec3_for_indices(std::ostream& out, const std::vector<Vec3>& values, const std::vector<int>& indices) {
    bool first = true;
    for (const int index : indices) {
        if (index < 0 || static_cast<std::size_t>(index) >= values.size()) {
            continue;
        }
        if (!first) {
            out << ',';
        }
        const Vec3& value = values[static_cast<std::size_t>(index)];
        out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
        first = false;
    }
}

void write_flat_vec2_for_indices(std::ostream& out, const std::vector<Vec2>& values, const std::vector<int>& indices) {
    bool first = true;
    for (const int index : indices) {
        if (index < 0 || static_cast<std::size_t>(index) >= values.size()) {
            continue;
        }
        if (!first) {
            out << ',';
        }
        const Vec2& value = values[static_cast<std::size_t>(index)];
        out << std::setprecision(17) << value[0] << ',' << value[1];
        first = false;
    }
}

std::vector<int> source_vertex_ids_for_indices(
    const std::vector<int>& indices,
    const std::vector<int>& source_vertex_map,
    std::size_t count
) {
    const std::size_t limit = std::min(count, indices.size());
    std::vector<int> result;
    result.reserve(limit);
    const bool has_source_map = !source_vertex_map.empty();
    for (std::size_t index = 0; index < limit; ++index) {
        const int vertex_index = indices[index];
        if (has_source_map
            && vertex_index >= 0
            && static_cast<std::size_t>(vertex_index) < source_vertex_map.size()) {
            result.push_back(source_vertex_map[static_cast<std::size_t>(vertex_index)]);
        } else {
            result.push_back(vertex_index);
        }
    }
    return result;
}

bool preview_source_vertex_range_for_indices(
    const std::vector<int>& indices,
    const std::vector<int>& source_vertex_map,
    std::size_t count,
    int source_vertex_start_hint,
    int& source_vertex_start
) {
    source_vertex_start = -1;
    if (count == 0) {
        return false;
    }
    if (source_vertex_map.empty() && source_vertex_start_hint >= 0) {
        source_vertex_start = source_vertex_start_hint;
        return true;
    }
    if (indices.size() < count) {
        return false;
    }
    int previous = -1;
    for (std::size_t index = 0; index < count; ++index) {
        const int vertex_index = indices[index];
        if (vertex_index < 0) {
            return false;
        }
        int source_vertex = vertex_index;
        if (!source_vertex_map.empty()) {
            if (static_cast<std::size_t>(vertex_index) >= source_vertex_map.size()) {
                return false;
            }
            source_vertex = source_vertex_map[static_cast<std::size_t>(vertex_index)];
        }
        if (source_vertex < 0) {
            return false;
        }
        if (index == 0) {
            source_vertex_start = source_vertex;
        } else if (source_vertex != previous + 1) {
            source_vertex_start = -1;
            return false;
        }
        previous = source_vertex;
    }
    return source_vertex_start >= 0;
}

void write_preview_source_vertex_ids(
    std::ostream& out,
    const std::vector<int>& source_indices,
    const std::string& source_indices_path = std::string()
) {
    int source_vertex_start = -1;
    if (contiguous_int_range(source_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << source_indices.size();
    } else if (!source_indices_path.empty()) {
        write_int_binary_file(source_indices_path, source_indices);
        out << ",\"source_vertex_indices_binary\":";
        write_preview_binary_descriptor(out, source_indices_path, source_indices.size(), 1, "i32");
    } else {
        out << ",\"source_vertex_indices\":[";
        for (std::size_t j = 0; j < source_indices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << source_indices[j];
        }
        out << ']';
    }
}

void write_preview_source_vertex_range(std::ostream& out, int source_vertex_start, std::size_t count) {
    out << ",\"source_vertex_start\":" << source_vertex_start
        << ",\"source_vertex_count\":" << count;
}

void write_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<int>& changed_vertices,
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& source_indices_path = std::string(),
    const std::vector<int>& source_vertex_map = std::vector<int>()
) {
    const std::vector<int> indices = valid_vertex_indices(changed_vertices, vertices.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    write_preview_source_vertex_ids(out, source_vertex_ids_for_indices(indices, source_vertex_map, indices.size()), source_indices_path);
    out << ",\"positions\":[";
    write_flat_vec3_for_indices(out, vertices, indices);
    out << "],\"normals\":[";
    if (normals.size() == vertices.size()) {
        write_flat_vec3_for_indices(out, normals, indices);
    }
    out << "],\"uvs\":[";
    if (uvs.size() == vertices.size()) {
        write_flat_vec2_for_indices(out, uvs, indices);
    }
    out << "]}";
}

void write_sparse_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<int>& changed_vertices,
    const std::vector<Vec3>& changed_positions,
    const std::vector<Vec3>& normals = {},
    const std::vector<Vec2>& uvs = {},
    const std::string& changed_positions_path = std::string(),
    int source_vertex_start = -1,
    const std::vector<int>& source_vertex_map = std::vector<int>()
) {
    const std::size_t count = std::min(changed_vertices.size(), changed_positions.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    std::vector<int> source_indices;
    int direct_source_start = -1;
    const bool direct_source_range = preview_source_vertex_range_for_indices(
        changed_vertices,
        source_vertex_map,
        count,
        source_vertex_start,
        direct_source_start
    );
    if (direct_source_range) {
        write_preview_source_vertex_range(out, direct_source_start, count);
    } else {
        source_indices = source_vertex_ids_for_indices(changed_vertices, source_vertex_map, count);
    }
    if (!changed_positions_path.empty()) {
        if (!direct_source_range) {
            write_preview_source_vertex_ids(
                out,
                source_indices,
                sibling_binary_path(changed_positions_path, ".source_indices.bin")
            );
        }
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, changed_positions_path, count, 3, "f64");
        if (!normals.empty()) {
            std::vector<Vec3> changed_normals;
            changed_normals.reserve(count);
            for (std::size_t index = 0; index < count; ++index) {
                const int vertex_index = changed_vertices[index];
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= normals.size()) {
                    changed_normals.clear();
                    break;
                }
                changed_normals.push_back(normals[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_normals.size() == count) {
                const std::string normals_path = sibling_binary_path(changed_positions_path, ".normals.bin");
                write_vec3_binary_file(normals_path, changed_normals);
                out << ",\"normals_binary\":";
                write_preview_binary_descriptor(out, normals_path, changed_normals.size(), 3, "f64");
            }
        }
        if (!uvs.empty()) {
            std::vector<Vec2> changed_uvs;
            changed_uvs.reserve(count);
            for (std::size_t index = 0; index < count; ++index) {
                const int vertex_index = changed_vertices[index];
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= uvs.size()) {
                    changed_uvs.clear();
                    break;
                }
                changed_uvs.push_back(uvs[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_uvs.size() == count) {
                const std::string uvs_path = sibling_binary_path(changed_positions_path, ".uvs.bin");
                write_vec2_binary_file(uvs_path, changed_uvs);
                out << ",\"uvs_binary\":";
                write_preview_binary_descriptor(out, uvs_path, changed_uvs.size(), 2, "f64");
            }
        }
        out << "}";
        return;
    }
    if (!direct_source_range) {
        write_preview_source_vertex_ids(out, source_indices);
    }
    out << ",\"positions\":[";
    for (std::size_t index = 0; index < count; ++index) {
        if (index > 0) {
            out << ',';
        }
        const Vec3& value = changed_positions[index];
        out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
    }
    out << "],\"normals\":[";
    if (!normals.empty()) {
        bool first = true;
        for (std::size_t index = 0; index < count; ++index) {
            const int vertex_index = changed_vertices[index];
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= normals.size()) {
                continue;
            }
            if (!first) {
                out << ',';
            }
            const Vec3& value = normals[static_cast<std::size_t>(vertex_index)];
            out << std::setprecision(17) << value[0] << ',' << value[1] << ',' << value[2];
            first = false;
        }
    }
    out << "],\"uvs\":[";
    if (!uvs.empty()) {
        bool first = true;
        for (std::size_t index = 0; index < count; ++index) {
            const int vertex_index = changed_vertices[index];
            if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= uvs.size()) {
                continue;
            }
            if (!first) {
                out << ',';
            }
            const Vec2& value = uvs[static_cast<std::size_t>(vertex_index)];
            out << std::setprecision(17) << value[0] << ',' << value[1];
            first = false;
        }
    }
    out << "]}";
}

void write_full_preview_vertex_update_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& positions_path,
    const std::vector<int>& source_vertex_map = std::vector<int>()
) {
    const std::size_t count = vertices.size();
    const std::vector<int> identity = identity_indices(count);
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << submesh_index;
    write_preview_source_vertex_ids(
        out,
        source_vertex_map.size() == count ? source_vertex_map : identity,
        positions_path.empty() ? std::string() : sibling_binary_path(positions_path, ".source_indices.bin")
    );
    if (!positions_path.empty()) {
        write_vec3_binary_file(positions_path, vertices);
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, positions_path, count, 3, "f64");
        if (normals.size() == count) {
            const std::string normals_path = sibling_binary_path(positions_path, ".normals.bin");
            write_vec3_binary_file(normals_path, normals);
            out << ",\"normals_binary\":";
            write_preview_binary_descriptor(out, normals_path, count, 3, "f64");
        }
        if (uvs.size() == count) {
            const std::string uvs_path = sibling_binary_path(positions_path, ".uvs.bin");
            write_vec2_binary_file(uvs_path, uvs);
            out << ",\"uvs_binary\":";
            write_preview_binary_descriptor(out, uvs_path, count, 2, "f64");
        }
        out << "}";
        return;
    }
    out << ",\"positions\":[";
    write_flat_vec3_for_indices(out, vertices, identity_indices(count));
    out << "],\"normals\":[";
    if (normals.size() == count) {
        write_flat_vec3_for_indices(out, normals, identity_indices(count));
    }
    out << "],\"uvs\":[";
    if (uvs.size() == count) {
        write_flat_vec2_for_indices(out, uvs, identity_indices(count));
    }
    out << "]}";
}

void write_preview_triangle_group(
    std::ostream& out,
    int submesh_index,
    const std::vector<Vec3>& vertices,
    const std::vector<std::array<int, 3>>& faces,
    const std::vector<Vec3>& normals,
    const std::vector<Vec2>& uvs,
    const std::string& preview_triangle_path = std::string(),
    const std::vector<int>& source_vertex_indices = std::vector<int>(),
    const std::vector<int>& source_face_indices = std::vector<int>()
) {
    const bool has_triangles = !vertices.empty() && !faces.empty();
    const std::vector<int> preview_source_vertex_indices = source_vertex_indices.size() == vertices.size()
        ? source_vertex_indices
        : identity_indices(vertices.size());
    const std::vector<int> preview_source_face_indices = source_face_indices.size() == faces.size()
        ? source_face_indices
        : identity_indices(faces.size());
    out << "{\"preview_backend\":\"cdmw_mesh_core\""
        << ",\"source_submesh_index\":" << submesh_index;
    if (has_triangles && !preview_triangle_path.empty()) {
        std::vector<int> indices;
        indices.reserve(faces.size() * 3u);
        for (const std::array<int, 3>& face : faces) {
            indices.push_back(face[0]);
            indices.push_back(face[1]);
            indices.push_back(face[2]);
        }
        const std::string normals_path = sibling_binary_path(preview_triangle_path, ".normals.bin");
        const std::string uvs_path = sibling_binary_path(preview_triangle_path, ".uvs.bin");
        const std::string indices_path = sibling_binary_path(preview_triangle_path, ".indices.bin");
        write_vec3_binary_file(preview_triangle_path, vertices);
        if (uvs.size() == vertices.size()) {
            write_vec2_binary_file(uvs_path, uvs);
        }
        if (normals.size() == vertices.size()) {
            write_vec3_binary_file(normals_path, normals);
        }
        write_int_binary_file(indices_path, indices);
        int source_vertex_start = -1;
        if (contiguous_int_range(preview_source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << preview_source_vertex_indices.size();
        } else {
            const std::string source_vertices_path = sibling_binary_path(preview_triangle_path, ".source_vertices.bin");
            write_int_binary_file(source_vertices_path, preview_source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_preview_binary_descriptor(out, source_vertices_path, preview_source_vertex_indices.size(), 1, "i32");
        }
        int source_face_start = -1;
        if (contiguous_int_range(preview_source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << preview_source_face_indices.size();
        } else {
            const std::string source_faces_path = sibling_binary_path(preview_triangle_path, ".source_faces.bin");
            write_int_binary_file(source_faces_path, preview_source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_preview_binary_descriptor(out, source_faces_path, preview_source_face_indices.size(), 1, "i32");
        }
        out << ",\"positions_binary\":";
        write_preview_binary_descriptor(out, preview_triangle_path, vertices.size(), 3, "f64");
        if (normals.size() == vertices.size()) {
            out << ",\"normals_binary\":";
            write_preview_binary_descriptor(out, normals_path, normals.size(), 3, "f64");
        }
        if (uvs.size() == vertices.size()) {
            out << ",\"uvs_binary\":";
            write_preview_binary_descriptor(out, uvs_path, uvs.size(), 2, "f64");
        }
        out << ",\"indices_binary\":";
        write_preview_binary_descriptor(out, indices_path, indices.size(), 1, "i32");
        out << '}';
        return;
    }
    int source_vertex_start = -1;
    if (has_triangles && contiguous_int_range(preview_source_vertex_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << preview_source_vertex_indices.size();
    } else {
        out << ",\"source_vertex_indices\":[";
        if (has_triangles) {
            for (std::size_t j = 0; j < vertices.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << preview_source_vertex_indices[j];
            }
        }
        out << ']';
    }
    int source_face_start = -1;
    if (has_triangles && contiguous_int_range(preview_source_face_indices, source_face_start)) {
        out << ",\"source_face_start\":" << source_face_start
            << ",\"source_face_count\":" << preview_source_face_indices.size();
    } else {
        out << ",\"source_face_indices\":[";
        for (std::size_t j = 0; j < faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << preview_source_face_indices[j];
        }
        out << ']';
    }
    out << ",\"positions\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < vertices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << vertices[j][0] << ',' << vertices[j][1] << ',' << vertices[j][2];
        }
    }
    out << "],\"normals\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < normals.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << normals[j][0] << ',' << normals[j][1] << ',' << normals[j][2];
        }
    }
    out << "],\"uvs\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < uvs.size() && j < vertices.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << std::setprecision(17) << uvs[j][0] << ',' << uvs[j][1];
        }
    }
    out << "],\"indices\":[";
    if (has_triangles) {
        for (std::size_t j = 0; j < faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << faces[j][0] << ',' << faces[j][1] << ',' << faces[j][2];
        }
    }
    out << "]}";
}

std::string preview_triangle_groups_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_triangle_groups\",\"groups\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("source_submesh_index"), int_or(item.get("index"), -1));
        if (submesh_index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        if (normals.size() != vertices.size() && !vertices.empty() && !faces.empty()) {
            normals = compute_smooth_normals(vertices, faces);
        }
        std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (uvs.size() > vertices.size()) {
            uvs.resize(vertices.size());
        }
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, vertices.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        if (!first) {
            out << ',';
        }
        first = false;
        write_preview_triangle_group(
            out,
            submesh_index,
            vertices,
            faces,
            normals,
            uvs,
            string_or(item.get("preview_triangle_output_path"), ""),
            source_vertices,
            source_faces
        );
    }
    out << "]}";
    return out.str();
}

std::string preview_vertex_update_groups_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_vertex_update_groups\",\"groups\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("source_submesh_index"), int_or(item.get("index"), -1));
        if (submesh_index < 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (vertices.empty()) {
            continue;
        }
        const std::vector<int> source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());
        const bool changed_all_vertices = bool_or(item.get("changed_all_vertices"), false);
        const std::string preview_vertex_path = string_or(item.get("preview_vertex_output_path"), "");
        const int changed_vertex_start = int_or(item.get("changed_vertex_start"), -1);
        const int changed_vertex_count = int_or(item.get("changed_vertex_count"), 0);
        const bool changed_vertex_range = changed_vertex_start >= 0
            && changed_vertex_count > 0
            && changed_vertex_start <= static_cast<int>(vertices.size())
            && changed_vertex_count <= static_cast<int>(vertices.size()) - changed_vertex_start;
        if (changed_all_vertices && !preview_vertex_path.empty()) {
            if (!first) {
                out << ',';
            }
            first = false;
            write_full_preview_vertex_update_group(
                out,
                submesh_index,
                vertices,
                mesh_normals_from_item(item),
                mesh_uvs_from_item(item),
                preview_vertex_path,
                source_vertex_map
            );
            continue;
        }
        std::vector<int> changed_vertices;
        if (changed_all_vertices) {
            changed_vertices.reserve(vertices.size());
            for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
                changed_vertices.push_back(static_cast<int>(vertex_index));
            }
        } else if (changed_vertex_range) {
            changed_vertices.reserve(static_cast<std::size_t>(changed_vertex_count));
            for (int offset = 0; offset < changed_vertex_count; ++offset) {
                changed_vertices.push_back(changed_vertex_start + offset);
            }
        } else {
            changed_vertices = int_vector_from_binary_or_json(item, "changed_vertices_binary", "changed_vertices");
        }
        if (changed_vertices.empty()) {
            changed_vertices = int_vector_from_binary_or_json(
                item,
                "source_vertex_indices_binary",
                "source_vertex_indices",
                "source_vertex_start",
                "source_vertex_count"
            );
        }
        changed_vertices = valid_vertex_indices(changed_vertices, vertices.size());
        if (changed_vertices.empty()) {
            continue;
        }
        std::vector<Vec3> changed_positions;
        changed_positions.reserve(changed_vertices.size());
        for (const int vertex_index : changed_vertices) {
            changed_positions.push_back(vertices[static_cast<std::size_t>(vertex_index)]);
        }
        if (!preview_vertex_path.empty()) {
            write_vec3_binary_file(preview_vertex_path, changed_positions);
        }
        if (!first) {
            out << ',';
        }
        first = false;
        write_sparse_preview_vertex_update_group(
            out,
            submesh_index,
            changed_vertices,
            changed_positions,
            mesh_normals_from_item(item),
            mesh_uvs_from_item(item),
            preview_vertex_path,
            changed_all_vertices ? 0 : (changed_vertex_range ? changed_vertex_start : -1),
            source_vertex_map
        );
    }
    out << "]}";
    return out.str();
}

std::vector<SubmeshPreviewDecimateResult> run_preview_decimate(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }

    std::vector<SubmeshPreviewDecimateResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        const int max_faces = int_or(item.get("max_faces"), 0);
        if (submesh_index < 0 || max_faces <= 0) {
            continue;
        }
        const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        if (vertices.empty() || faces.size() <= static_cast<std::size_t>(max_faces)) {
            continue;
        }

        SubmeshPreviewDecimateResult result;
        result.index = submesh_index;
        result.vertices_path = string_or(item.get("vertices_output_path"), "");
        result.faces_path = string_or(item.get("faces_output_path"), "");
        result.uvs_path = string_or(item.get("uvs_output_path"), "");
        result.normals_path = string_or(item.get("normals_output_path"), "");
        result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");

        const std::size_t step = std::max<std::size_t>(1, (faces.size() + static_cast<std::size_t>(max_faces) - 1u) / static_cast<std::size_t>(max_faces));
        std::map<int, int> source_to_preview;
        std::vector<int> source_remap;
        source_remap.reserve(static_cast<std::size_t>(max_faces) * 3u);
        result.faces.reserve(static_cast<std::size_t>(max_faces));
        result.vertices.reserve(static_cast<std::size_t>(max_faces) * 3u);

        for (std::size_t face_index = 0; face_index < faces.size() && result.faces.size() < static_cast<std::size_t>(max_faces); face_index += step) {
            std::array<int, 3> remapped_face{0, 0, 0};
            bool valid_face = true;
            for (std::size_t corner = 0; corner < 3; ++corner) {
                const int source_index = faces[face_index][corner];
                if (source_index < 0 || static_cast<std::size_t>(source_index) >= vertices.size()) {
                    valid_face = false;
                    break;
                }
                auto found = source_to_preview.find(source_index);
                if (found == source_to_preview.end()) {
                    const int preview_index = static_cast<int>(result.vertices.size());
                    source_to_preview[source_index] = preview_index;
                    source_remap.push_back(source_index);
                    result.vertices.push_back(vertices[static_cast<std::size_t>(source_index)]);
                    remapped_face[corner] = preview_index;
                } else {
                    remapped_face[corner] = found->second;
                }
            }
            if (valid_face) {
                result.faces.push_back(remapped_face);
            }
        }

        if (result.faces.empty()) {
            continue;
        }

        const std::vector<Vec2> uvs = mesh_uvs_from_item(item);
        if (uvs.size() == vertices.size()) {
            result.uvs = copy_values_by_vertex_remap(uvs, source_remap);
        }
        const std::vector<Vec3> normals = mesh_normals_from_item(item);
        if (normals.size() == vertices.size()) {
            result.normals = copy_values_by_vertex_remap(normals, source_remap);
        }
        const BoneAssignments bones = mesh_bones_from_item(item);
        if (valid_bone_assignments(bones) && bones.indices.size() == vertices.size()) {
            result.bones = copy_bones_by_vertex_remap(bones, source_remap);
        }
        const std::vector<int> source_vertex_map = int_vector_from_binary_or_json(
            item,
            "source_vertex_map_binary",
            "source_vertex_map",
            "source_vertex_map_start",
            "source_vertex_map_count"
        );
        if (source_vertex_map.size() == vertices.size()) {
            result.source_vertex_map = copy_values_by_vertex_remap(source_vertex_map, source_remap);
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::string preview_decimate_report_json(const JsonValue& root) {
    const std::vector<SubmeshPreviewDecimateResult> results = run_preview_decimate(root);
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_decimate\",\"submeshes\":[";
    for (std::size_t index = 0; index < results.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        const SubmeshPreviewDecimateResult& result = results[index];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertices.size()
            << ",\"face_count\":" << result.faces.size();
        if (!result.vertices_path.empty()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        }
        if (!result.faces_path.empty()) {
            std::vector<int> flat_faces;
            flat_faces.reserve(result.faces.size() * 3u);
            for (const std::array<int, 3>& face : result.faces) {
                flat_faces.push_back(face[0]);
                flat_faces.push_back(face[1]);
                flat_faces.push_back(face[2]);
            }
            write_int_binary_file(result.faces_path, flat_faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        }
        if (!result.uvs_path.empty() && result.uvs.size() == result.vertices.size()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && valid_bone_assignments(result.bones)
            && result.bones.indices.size() == result.vertices.size()) {
            const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (bone_counts.size() == result.vertices.size() && flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(result.bone_counts_path, bone_counts);
                write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
            }
        }
        if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
            write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
            out << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string merge_submeshes_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }

    struct MergeInput {
        std::vector<Vec3> vertices;
        std::vector<std::array<int, 3>> faces;
        std::vector<Vec3> normals;
        std::vector<Vec2> uvs;
    };

    std::vector<MergeInput> inputs;
    inputs.reserve(submeshes->array_value.size());
    bool wants_normals = false;
    bool wants_uvs = false;
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        MergeInput input;
        input.vertices = mesh_vertices_from_item(item);
        input.faces = mesh_faces_from_item(item, input.vertices.size());
        input.normals = mesh_normals_from_item(item);
        input.uvs = mesh_uvs_from_item(item);
        if (input.normals.size() == input.vertices.size() && !input.vertices.empty()) {
            wants_normals = true;
        }
        if (input.uvs.size() == input.vertices.size() && !input.vertices.empty()) {
            wants_uvs = true;
        }
        vertex_count += input.vertices.size();
        face_count += input.faces.size();
        inputs.push_back(std::move(input));
    }

    std::vector<Vec3> merged_vertices;
    std::vector<std::array<int, 3>> merged_faces;
    std::vector<Vec3> merged_normals;
    std::vector<Vec2> merged_uvs;
    merged_vertices.reserve(vertex_count);
    merged_faces.reserve(face_count);
    if (wants_normals) {
        merged_normals.reserve(vertex_count);
    }
    if (wants_uvs) {
        merged_uvs.reserve(vertex_count);
    }

    int base = 0;
    for (const MergeInput& input : inputs) {
        merged_vertices.insert(merged_vertices.end(), input.vertices.begin(), input.vertices.end());
        if (wants_normals) {
            if (input.normals.size() == input.vertices.size()) {
                merged_normals.insert(merged_normals.end(), input.normals.begin(), input.normals.end());
            } else {
                merged_normals.insert(merged_normals.end(), input.vertices.size(), Vec3{0.0, 1.0, 0.0});
            }
        }
        if (wants_uvs) {
            if (input.uvs.size() == input.vertices.size()) {
                merged_uvs.insert(merged_uvs.end(), input.uvs.begin(), input.uvs.end());
            } else {
                merged_uvs.insert(merged_uvs.end(), input.vertices.size(), Vec2{0.0, 0.0});
            }
        }
        for (const std::array<int, 3>& face : input.faces) {
            merged_faces.push_back({face[0] + base, face[1] + base, face[2] + base});
        }
        base += static_cast<int>(input.vertices.size());
    }
    if (merged_normals.size() != merged_vertices.size()) {
        merged_normals = compute_smooth_normals(merged_vertices, merged_faces);
    }

    const std::string vertices_path = string_or(root.get("vertices_output_path"), "");
    const std::string faces_path = string_or(root.get("faces_output_path"), "");
    const std::string normals_path = string_or(root.get("normals_output_path"), "");
    const std::string uvs_path = string_or(root.get("uvs_output_path"), "");
    if (!vertices_path.empty()) {
        write_vec3_binary_file(vertices_path, merged_vertices);
    }
    if (!faces_path.empty()) {
        std::vector<int> merged_face_indices;
        merged_face_indices.reserve(merged_faces.size() * 3u);
        for (const std::array<int, 3>& face : merged_faces) {
            merged_face_indices.push_back(face[0]);
            merged_face_indices.push_back(face[1]);
            merged_face_indices.push_back(face[2]);
        }
        write_int_binary_file(faces_path, merged_face_indices);
    }
    if (!normals_path.empty()) {
        write_vec3_binary_file(normals_path, merged_normals);
    }
    if (!uvs_path.empty() && merged_uvs.size() == merged_vertices.size()) {
        write_vec2_binary_file(uvs_path, merged_uvs);
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"merge_submeshes\""
        << ",\"vertex_count\":" << merged_vertices.size()
        << ",\"face_count\":" << merged_faces.size();
    if (!vertices_path.empty()) {
        out << ",\"vertices_binary\":";
        write_vec3_binary_descriptor(out, vertices_path, merged_vertices.size());
    }
    if (!faces_path.empty()) {
        out << ",\"faces_binary\":";
        write_int_binary_descriptor(out, faces_path, merged_faces.size(), 3);
    }
    if (!normals_path.empty()) {
        out << ",\"normals_binary\":";
        write_vec3_binary_descriptor(out, normals_path, merged_normals.size());
    }
    if (!uvs_path.empty() && merged_uvs.size() == merged_vertices.size()) {
        out << ",\"uvs_binary\":";
        write_vec2_binary_descriptor(out, uvs_path, merged_uvs.size());
    }
    out << '}';
    return out.str();
}

Vec3 bounds_center_for_vertices(const std::vector<Vec3>& vertices) {
    if (vertices.empty()) {
        return {0.0, 0.0, 0.0};
    }
    Vec3 minimum = vertices.front();
    Vec3 maximum = vertices.front();
    for (const Vec3& vertex : vertices) {
        for (int axis = 0; axis < 3; ++axis) {
            minimum[axis] = std::min(minimum[axis], vertex[axis]);
            maximum[axis] = std::max(maximum[axis], vertex[axis]);
        }
    }
    return {
        (minimum[0] + maximum[0]) * 0.5,
        (minimum[1] + maximum[1]) * 0.5,
        (minimum[2] + maximum[2]) * 0.5,
    };
}

Transform source_part_adjustment_transform(const JsonValue& adjustment, const std::vector<Vec3>& vertices) {
    Transform transform;
    transform.translate = vec3_or(adjustment.get("offset_xyz"), transform.translate);
    transform.scale = vec3_or(adjustment.get("scale_xyz"), transform.scale);
    const double uniform = number_or(adjustment.get("uniform_scale"), 1.0);
    transform.scale = {
        transform.scale[0] * uniform,
        transform.scale[1] * uniform,
        transform.scale[2] * uniform,
    };
    transform.rotate = vec3_or(adjustment.get("rotate_xyz_degrees"), transform.rotate);
    const std::vector<Vec3> pivot_vertices = vertices_from_binary_or_json(
        adjustment,
        "pivot_vertices_binary",
        "pivot_vertices"
    );
    const Vec3 default_pivot = pivot_vertices.empty()
        ? bounds_center_for_vertices(vertices)
        : bounds_center_for_vertices(pivot_vertices);
    transform.pivot = adjustment.get("pivot") != nullptr
        ? vec3_or(adjustment.get("pivot"), default_pivot)
        : default_pivot;
    return transform;
}

std::string affine_transform_report_json(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"affine_transform\",\"submeshes\":[";
    bool first = true;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int submesh_index = int_or(item.get("index"), -1);
        if (submesh_index < 0) {
            continue;
        }
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        const JsonValue* source_part_adjustment = item.get("source_part_adjustment");
        const bool has_source_part_adjustment = source_part_adjustment != nullptr
            && source_part_adjustment->type == JsonValue::Type::Object;
        Transform source_part_transform;
        if (has_source_part_adjustment) {
            source_part_transform = source_part_adjustment_transform(*source_part_adjustment, vertices);
            for (Vec3& vertex : vertices) {
                vertex = transform_vertex(vertex, source_part_transform);
            }
        } else {
            std::vector<double> matrix = double_vector_from_json(item.get("position_matrix"));
            if (matrix.size() != 12) {
                throw std::runtime_error("position_matrix must contain 12 values");
            }
            for (const double value : matrix) {
                if (!std::isfinite(value)) {
                    throw std::runtime_error("non-finite position_matrix value");
                }
            }
            for (Vec3& vertex : vertices) {
                const double x = vertex[0];
                const double y = vertex[1];
                const double z = vertex[2];
                vertex = {
                    matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
                    matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
                    matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
                };
            }
        }

        std::vector<Vec3> normals = mesh_normals_from_item(item);
        std::vector<double> normal_matrix = double_vector_from_json(item.get("normal_matrix"));
        if (!normal_matrix.empty() && normal_matrix.size() != 9) {
            throw std::runtime_error("normal_matrix must contain 9 values");
        }
        if (normal_matrix.size() == 9 && normals.size() == vertices.size()) {
            for (Vec3& normal : normals) {
                const double x = normal[0];
                const double y = normal[1];
                const double z = normal[2];
                normal = normalized_vec3(
                    {
                        normal_matrix[0] * x + normal_matrix[1] * y + normal_matrix[2] * z,
                        normal_matrix[3] * x + normal_matrix[4] * y + normal_matrix[5] * z,
                        normal_matrix[6] * x + normal_matrix[7] * y + normal_matrix[8] * z,
                    },
                    {0.0, 1.0, 0.0}
                );
            }
        } else if (has_source_part_adjustment && normals.size() == vertices.size()) {
            Transform normal_transform;
            normal_transform.rotate = source_part_transform.rotate;
            for (Vec3& normal : normals) {
                normal = normalized_vec3(transform_vertex(normal, normal_transform), {0.0, 1.0, 0.0});
            }
        } else {
            normals.clear();
        }

        const bool mirror_x_around_bounds_center = bool_or(item.get("mirror_x_around_bounds_center"), false);
        if (mirror_x_around_bounds_center && !vertices.empty()) {
            const double plane_x = bounds_center_for_vertices(vertices)[0];
            for (Vec3& vertex : vertices) {
                vertex[0] = 2.0 * plane_x - vertex[0];
            }
            if (normals.size() == vertices.size()) {
                for (Vec3& normal : normals) {
                    normal[0] = -normal[0];
                    normal = normalized_vec3(normal, {0.0, 1.0, 0.0});
                }
            }
        }

        std::vector<std::array<int, 3>> faces;
        const bool reverse_face_winding = bool_or(item.get("reverse_face_winding"), false)
            || mirror_x_around_bounds_center;
        const std::string faces_path = string_or(item.get("faces_output_path"), "");
        if (reverse_face_winding || !faces_path.empty()) {
            faces = faces_from_binary_or_json(item, vertices.size());
            if (reverse_face_winding) {
                for (std::array<int, 3>& face : faces) {
                    std::swap(face[1], face[2]);
                }
            }
        }

        const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        if (!vertices_path.empty()) {
            write_vec3_binary_file(vertices_path, vertices);
        }
        if (!normals_path.empty() && normals.size() == vertices.size()) {
            write_vec3_binary_file(normals_path, normals);
        }
        if (!faces_path.empty()) {
            write_faces_binary_file(faces_path, faces);
        }
        if (!first) {
            out << ',';
        }
        first = false;
        out << "{\"index\":" << submesh_index
            << ",\"vertex_count\":" << vertices.size();
        if (!faces_path.empty()) {
            out << ",\"face_count\":" << faces.size();
        }
        if (!vertices_path.empty()) {
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, vertices_path, vertices.size());
        }
        if (!normals_path.empty() && normals.size() == vertices.size()) {
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, normals_path, normals.size());
        }
        if (!faces_path.empty()) {
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, faces_path, faces.size(), 3);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string string_from_ufbx(ufbx_string value) {
    if (value.data == nullptr || value.length == 0) {
        return std::string();
    }
    return std::string(value.data, value.length);
}

void write_string_array(std::ostream& out, const std::vector<std::string>& values) {
    out << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_escaped(out, values[i]);
    }
    out << ']';
}

std::string import_scene_report_json(const JsonValue& root) {
    const std::string source_path = string_or(root.get("source_path"));
    if (source_path.empty()) {
        throw std::runtime_error("source_path is required");
    }

    ufbx_load_opts opts = {};
    opts.generate_missing_normals = true;
    ufbx_error error = {};
    ufbx_scene* scene = ufbx_load_file_len(source_path.c_str(), source_path.size(), &opts, &error);
    if (scene == nullptr) {
        std::ostringstream out;
        out << "{\"status\":\"failed\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"import_scene\",\"import_backend\":\"ufbx\",\"source_path\":";
        write_escaped(out, source_path);
        out << ",\"error\":";
        write_escaped(out, string_from_ufbx(error.description));
        out << "}";
        return out.str();
    }

    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    std::size_t triangle_count = 0;
    std::size_t index_count = 0;
    bool has_uvs = false;
    bool has_normals = false;
    bool has_tangents = false;
    std::size_t max_weights_per_vertex = 0;
    for (std::size_t i = 0; i < scene->meshes.count; ++i) {
        const ufbx_mesh* mesh = scene->meshes.data[i];
        if (mesh == nullptr) {
            continue;
        }
        vertex_count += mesh->num_vertices;
        face_count += mesh->num_faces;
        triangle_count += mesh->num_triangles;
        index_count += mesh->num_indices;
        has_uvs = has_uvs || mesh->vertex_uv.exists;
        has_normals = has_normals || mesh->vertex_normal.exists;
        has_tangents = has_tangents || mesh->vertex_tangent.exists;
        for (std::size_t j = 0; j < mesh->skin_deformers.count; ++j) {
            const ufbx_skin_deformer* skin = mesh->skin_deformers.data[j];
            if (skin != nullptr && skin->max_weights_per_vertex > max_weights_per_vertex) {
                max_weights_per_vertex = skin->max_weights_per_vertex;
            }
        }
    }

    std::vector<std::string> material_names;
    for (std::size_t i = 0; i < scene->materials.count && material_names.size() < 64; ++i) {
        const ufbx_material* material = scene->materials.data[i];
        const std::string name = material != nullptr ? string_from_ufbx(material->name) : std::string();
        material_names.push_back(name.empty() ? std::string("material_") + std::to_string(i) : name);
    }

    std::vector<std::string> texture_files;
    for (std::size_t i = 0; i < scene->texture_files.count && texture_files.size() < 64; ++i) {
        const ufbx_texture_file& texture = scene->texture_files.data[i];
        std::string filename = string_from_ufbx(texture.filename);
        if (filename.empty()) {
            filename = string_from_ufbx(texture.relative_filename);
        }
        if (!filename.empty()) {
            texture_files.push_back(filename);
        }
    }

    std::vector<std::string> animation_names;
    for (std::size_t i = 0; i < scene->anim_stacks.count && animation_names.size() < 64; ++i) {
        const ufbx_anim_stack* stack = scene->anim_stacks.data[i];
        const std::string name = stack != nullptr ? string_from_ufbx(stack->name) : std::string();
        animation_names.push_back(name.empty() ? std::string("animation_") + std::to_string(i) : name);
    }

    std::vector<std::string> unsupported;
    if (scene->skin_deformers.count || scene->bones.count || scene->skin_clusters.count) {
        unsupported.push_back("fbx_rig_mapping_report_only");
    }
    if (scene->anim_stacks.count || scene->anim_layers.count || scene->anim_curves.count) {
        unsupported.push_back("fbx_animation_report_only");
    }
    if (scene->blend_deformers.count || scene->blend_shapes.count) {
        unsupported.push_back("fbx_blend_shapes_report_only");
    }
    if (scene->cache_deformers.count || scene->cache_files.count) {
        unsupported.push_back("fbx_geometry_cache_report_only");
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"import_scene\",\"import_backend\":\"ufbx\",\"source_path\":";
    write_escaped(out, source_path);
    out << ",\"source_format\":\"fbx\",\"crimson_compatibility\":\"unmapped\",\"mesh\":{"
        << "\"part_count\":" << scene->meshes.count
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"triangle_count\":" << triangle_count
        << ",\"index_count\":" << index_count
        << ",\"has_uvs\":" << (has_uvs ? "true" : "false")
        << ",\"has_normals\":" << (has_normals ? "true" : "false")
        << ",\"has_tangents\":" << (has_tangents ? "true" : "false")
        << "},\"materials\":{\"count\":" << scene->materials.count << ",\"names\":";
    write_string_array(out, material_names);
    out << "},\"texture_hints\":{\"count\":" << scene->texture_files.count << ",\"files\":";
    write_string_array(out, texture_files);
    out << "},\"skeleton_hints\":{"
        << "\"has_skinning\":" << (scene->skin_deformers.count ? "true" : "false")
        << ",\"bone_count\":" << scene->bones.count
        << ",\"skin_deformer_count\":" << scene->skin_deformers.count
        << ",\"skin_cluster_count\":" << scene->skin_clusters.count
        << ",\"max_weights_per_vertex\":" << max_weights_per_vertex
        << ",\"rig_status\":";
    write_escaped(out, (scene->skin_deformers.count || scene->bones.count) ? "reported_unsupported_until_crimson_mapping" : "none");
    out << ",\"animation_status\":";
    write_escaped(out, scene->anim_stacks.count ? "reported_unsupported_until_crimson_mapping" : "none");
    out << "},\"animations\":{\"count\":" << scene->anim_stacks.count << ",\"names\":";
    write_string_array(out, animation_names);
    out << "},\"unsupported\":";
    write_string_array(out, unsupported);
    out << ",\"diagnostics\":[";
    write_escaped(out, "FBX parsed with ufbx; Crimson compatibility remains unmapped until assigned to a target asset.");
    if (!unsupported.empty()) {
        out << ',';
        write_escaped(out, "Rig, animation, blend shape, or cache data is reported only and not imported into game-ready output.");
    }
    out << "]}";
    ufbx_free_scene(scene);
    return out.str();
}

std::string tangent_backend_summary(const std::vector<SubmeshTangentsResult>& results) {
    if (results.empty()) {
        return "none";
    }
    std::string backend = results.front().tangent_backend;
    for (const SubmeshTangentsResult& result : results) {
        if (result.tangent_backend != backend) {
            return "mixed";
        }
    }
    return backend;
}

void write_command_metrics(std::ostream& out, double cpp_ms) {
    out << "\"metrics\":{\"cpp_ms\":" << cpp_ms
        << ",\"io_serialization_ms\":0,\"python_apply_ms\":0,\"d3d11_update_ms\":0}";
}

std::string selection_report_json(const std::vector<SubmeshSelectionResult>& results, double cpp_ms = 0.0) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionResult& result = results[i];
        out << "{\"index\":" << result.index;
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":[";
            for (std::size_t j = 0; j < result.selected_vertices.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << result.selected_vertices[j];
            }
            out << ']';
        }
        out << "}";
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string uv_selection_report_json(const std::vector<SubmeshUvSelectionResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_selection\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshUvSelectionResult& result = results[i];
        out << "{\"index\":" << result.index;
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":";
            write_int_vector(out, result.selected_vertices);
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string uv_summary_report_json(const std::vector<UvIslandSummaryResult>& islands) {
    std::ostringstream out;
    int selected_count = 0;
    for (const UvIslandSummaryResult& island : islands) {
        if (island.selected) {
            ++selected_count;
        }
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_summary\""
        << ",\"island_count\":" << islands.size()
        << ",\"selected_island_count\":" << selected_count
        << ",\"islands\":[";
    for (std::size_t i = 0; i < islands.size(); ++i) {
        if (i) {
            out << ',';
        }
        const UvIslandSummaryResult& island = islands[i];
        out << "{\"index\":" << island.index
            << ",\"submesh_index\":" << island.submesh_index
            << ",\"part_name\":";
        write_escaped(out, island.part_name);
        out << ",\"material\":";
        write_escaped(out, island.material);
        out << ",\"texture\":";
        write_escaped(out, island.texture);
        out << ",\"vertex_count\":" << island.vertex_count
            << ",\"face_count\":" << island.face_count
            << ",\"uv_min\":[" << island.uv_min[0] << ',' << island.uv_min[1] << ']'
            << ",\"uv_max\":[" << island.uv_max[0] << ',' << island.uv_max[1] << ']'
            << ",\"selected\":" << (island.selected ? "true" : "false")
            << ",\"selected_vertex_count\":" << island.selected_vertex_count
            << ",\"selected_face_count\":" << island.selected_face_count
            << '}';
    }
    out << "]}";
    return out.str();
}

std::string mesh_metadata_report_json(const std::vector<SubmeshMetadataResult>& results) {
    std::size_t total_vertices = 0;
    std::size_t total_faces = 0;
    bool has_uvs = false;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
    for (const SubmeshMetadataResult& result : results) {
        total_vertices += result.vertex_count;
        total_faces += result.face_count;
        has_uvs = has_uvs || result.has_uvs;
        if (!result.has_bounds) {
            continue;
        }
        if (!has_bounds) {
            bbox_min = result.bbox_min;
            bbox_max = result.bbox_max;
            has_bounds = true;
        } else {
            bbox_min[0] = std::min(bbox_min[0], result.bbox_min[0]);
            bbox_min[1] = std::min(bbox_min[1], result.bbox_min[1]);
            bbox_min[2] = std::min(bbox_min[2], result.bbox_min[2]);
            bbox_max[0] = std::max(bbox_max[0], result.bbox_max[0]);
            bbox_max[1] = std::max(bbox_max[1], result.bbox_max[1]);
            bbox_max[2] = std::max(bbox_max[2], result.bbox_max[2]);
        }
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_metadata\""
        << ",\"submesh_count\":" << results.size()
        << ",\"total_vertices\":" << total_vertices
        << ",\"total_faces\":" << total_faces
        << ",\"has_uvs\":" << (has_uvs ? "true" : "false")
        << ",\"has_bounds\":" << (has_bounds ? "true" : "false")
        << ",\"bbox_min\":";
    write_vec3(out, has_bounds ? bbox_min : Vec3{0.0, 0.0, 0.0});
    out << ",\"bbox_max\":";
    write_vec3(out, has_bounds ? bbox_max : Vec3{0.0, 0.0, 0.0});
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshMetadataResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"vertex_count\":" << result.vertex_count
            << ",\"face_count\":" << result.face_count
            << ",\"has_uvs\":" << (result.has_uvs ? "true" : "false")
            << ",\"has_bounds\":" << (result.has_bounds ? "true" : "false")
            << ",\"bbox_min\":";
        write_vec3(out, result.has_bounds ? result.bbox_min : Vec3{0.0, 0.0, 0.0});
        out << ",\"bbox_max\":";
        write_vec3(out, result.has_bounds ? result.bbox_max : Vec3{0.0, 0.0, 0.0});
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string selection_bounds_report_json(const std::vector<SubmeshSelectionBoundsResult>& results) {
    std::size_t selected_vertex_count = 0;
    bool has_bounds = false;
    Vec3 bbox_min{0.0, 0.0, 0.0};
    Vec3 bbox_max{0.0, 0.0, 0.0};
    for (const SubmeshSelectionBoundsResult& result : results) {
        selected_vertex_count += result.selected_vertex_count;
        if (!result.has_bounds) {
            continue;
        }
        if (!has_bounds) {
            bbox_min = result.bbox_min;
            bbox_max = result.bbox_max;
            has_bounds = true;
        } else {
            bbox_min[0] = std::min(bbox_min[0], result.bbox_min[0]);
            bbox_min[1] = std::min(bbox_min[1], result.bbox_min[1]);
            bbox_min[2] = std::min(bbox_min[2], result.bbox_min[2]);
            bbox_max[0] = std::max(bbox_max[0], result.bbox_max[0]);
            bbox_max[1] = std::max(bbox_max[1], result.bbox_max[1]);
            bbox_max[2] = std::max(bbox_max[2], result.bbox_max[2]);
        }
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_bounds\""
        << ",\"submesh_count\":" << results.size()
        << ",\"selected_vertex_count\":" << selected_vertex_count
        << ",\"has_bounds\":" << (has_bounds ? "true" : "false")
        << ",\"bbox_min\":";
    write_vec3(out, has_bounds ? bbox_min : Vec3{0.0, 0.0, 0.0});
    out << ",\"bbox_max\":";
    write_vec3(out, has_bounds ? bbox_max : Vec3{0.0, 0.0, 0.0});
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionBoundsResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"selected_vertex_count\":" << result.selected_vertex_count
            << ",\"has_bounds\":" << (result.has_bounds ? "true" : "false")
            << ",\"bbox_min\":";
        write_vec3(out, result.has_bounds ? result.bbox_min : Vec3{0.0, 0.0, 0.0});
        out << ",\"bbox_max\":";
        write_vec3(out, result.has_bounds ? result.bbox_max : Vec3{0.0, 0.0, 0.0});
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::vector<int> flatten_selection_edges(const std::vector<std::array<int, 2>>& edges) {
    std::vector<int> values;
    values.reserve(edges.size() * 2u);
    for (const auto& edge : edges) {
        values.push_back(edge[0]);
        values.push_back(edge[1]);
    }
    return values;
}

std::vector<int> flatten_vertex_blend_indices(const std::vector<VertexBlend>& blends) {
    std::vector<int> values;
    values.reserve(blends.size() * 3u);
    for (const VertexBlend& blend : blends) {
        values.push_back(blend.index);
        values.push_back(blend.left);
        values.push_back(blend.right);
    }
    return values;
}

std::vector<double> flatten_vertex_blend_factors(const std::vector<VertexBlend>& blends) {
    std::vector<double> values;
    values.reserve(blends.size());
    for (const VertexBlend& blend : blends) {
        values.push_back(blend.factor);
    }
    return values;
}

void write_selection_preview_group(std::ostream& out, const SubmeshSelectionPreviewResult& result) {
    out << "{\"preview_backend\":\"cdmw_mesh_core\",\"source_submesh_index\":" << result.index;
    if (!result.selection_preview_path.empty()) {
        const std::string source_edges_path = sibling_binary_path(result.selection_preview_path, ".source_edges.bin");
        const std::string source_faces_path = sibling_binary_path(result.selection_preview_path, ".source_faces.bin");
        int source_vertex_start = -1;
        if (contiguous_int_range(result.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << result.source_vertex_indices.size();
        } else {
            write_int_binary_file(result.selection_preview_path, result.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_preview_binary_descriptor(out, result.selection_preview_path, result.source_vertex_indices.size(), 1, "i32");
        }
        if (!result.source_edges.empty()) {
            write_int_binary_file(source_edges_path, flatten_selection_edges(result.source_edges));
            out << ",\"source_edges_binary\":";
            write_preview_binary_descriptor(out, source_edges_path, result.source_edges.size(), 2, "i32");
        }
        if (!result.source_face_indices.empty()) {
            int source_face_start = -1;
            if (contiguous_int_range(result.source_face_indices, source_face_start)) {
                out << ",\"source_face_start\":" << source_face_start
                    << ",\"source_face_count\":" << result.source_face_indices.size();
            } else {
                write_int_binary_file(source_faces_path, result.source_face_indices);
                out << ",\"source_face_indices_binary\":";
                write_preview_binary_descriptor(out, source_faces_path, result.source_face_indices.size(), 1, "i32");
            }
        }
        out << '}';
        return;
    }
    int source_vertex_start = -1;
    if (contiguous_int_range(result.source_vertex_indices, source_vertex_start)) {
        out << ",\"source_vertex_start\":" << source_vertex_start
            << ",\"source_vertex_count\":" << result.source_vertex_indices.size();
    } else {
        out << ",\"source_vertex_indices\":";
        write_int_vector(out, result.source_vertex_indices);
    }
    if (!result.source_edges.empty()) {
        out << ",\"source_edges\":[";
        for (std::size_t edge_index = 0; edge_index < result.source_edges.size(); ++edge_index) {
            if (edge_index) {
                out << ',';
            }
            out << '[' << result.source_edges[edge_index][0] << ',' << result.source_edges[edge_index][1] << ']';
        }
        out << ']';
    }
    if (!result.source_face_indices.empty()) {
        int source_face_start = -1;
        if (contiguous_int_range(result.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << result.source_face_indices.size();
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, result.source_face_indices);
        }
    }
    out << '}';
}

std::string selection_preview_report_json(const std::vector<SubmeshSelectionPreviewResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_preview\",\"groups\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshSelectionPreviewResult& result = results[i];
        write_selection_preview_group(out, result);
    }
    out << "]}";
    return out.str();
}

void write_selection_prune_item(std::ostream& out, const SubmeshSelectionPruneResult& result) {
    out << "{\"index\":" << result.index;
    if (!result.selected_vertices.empty()) {
        int selected_vertex_start = -1;
        if (contiguous_int_range(result.selected_vertices, selected_vertex_start)) {
            out << ",\"selected_vertex_start\":" << selected_vertex_start
                << ",\"selected_vertex_count\":" << result.selected_vertices.size();
        } else if (!result.selected_vertices_path.empty()) {
            write_int_binary_file(result.selected_vertices_path, result.selected_vertices);
            out << ",\"selected_vertices_binary\":";
            write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1);
        } else {
            out << ",\"selected_vertices\":";
            write_int_vector(out, result.selected_vertices);
        }
    }
    if (!result.selected_edges.empty()) {
        if (!result.selected_edges_path.empty()) {
            write_int_binary_file(result.selected_edges_path, flatten_selection_edges(result.selected_edges));
            out << ",\"selected_edges_binary\":";
            write_int_binary_descriptor(out, result.selected_edges_path, result.selected_edges.size(), 2);
        } else {
            out << ",\"selected_edges\":[";
            for (std::size_t edge_index = 0; edge_index < result.selected_edges.size(); ++edge_index) {
                if (edge_index) {
                    out << ',';
                }
                out << '[' << result.selected_edges[edge_index][0] << ',' << result.selected_edges[edge_index][1] << ']';
            }
            out << ']';
        }
    }
    if (!result.selected_faces.empty()) {
        int selected_face_start = -1;
        if (contiguous_int_range(result.selected_faces, selected_face_start)) {
            out << ",\"selected_face_start\":" << selected_face_start
                << ",\"selected_face_count\":" << result.selected_faces.size();
        } else if (!result.selected_faces_path.empty()) {
            write_int_binary_file(result.selected_faces_path, result.selected_faces);
            out << ",\"selected_faces_binary\":";
            write_int_binary_descriptor(out, result.selected_faces_path, result.selected_faces.size(), 1);
        } else {
            out << ",\"selected_faces\":";
            write_int_vector(out, result.selected_faces);
        }
    }
    out << '}';
}

std::string selection_prune_report_json(const std::vector<SubmeshSelectionPruneResult>& results, double cpp_ms = 0.0) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"selection_prune\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_prune_item(out, results[i]);
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

std::string mesh_editor_delta_path(
    const std::string& directory,
    const std::string& session_id,
    int submesh_index,
    const std::string& role,
    const std::string& suffix
);

std::vector<SubmeshSelectionPruneResult> mesh_editor_selection_report_items(
    const MeshEditorSelection& selection,
    const std::string& output_dir,
    const std::string& session_id
) {
    std::set<int> targets;
    for (const auto& mapping : {selection.vertices, selection.faces}) {
        for (const auto& entry : mapping) {
            targets.insert(entry.first);
        }
    }
    for (const auto& entry : selection.edges) {
        targets.insert(entry.first);
    }
    std::vector<SubmeshSelectionPruneResult> results;
    for (const int submesh_index : targets) {
        SubmeshSelectionPruneResult result;
        result.index = submesh_index;
        const auto vertices = selection.vertices.find(submesh_index);
        if (vertices != selection.vertices.end()) {
            result.selected_vertices.assign(vertices->second.begin(), vertices->second.end());
        }
        const auto edges = selection.edges.find(submesh_index);
        if (edges != selection.edges.end()) {
            result.selected_edges.assign(edges->second.begin(), edges->second.end());
        }
        const auto faces = selection.faces.find(submesh_index);
        if (faces != selection.faces.end()) {
            result.selected_faces.assign(faces->second.begin(), faces->second.end());
        }
        if (!output_dir.empty()) {
            result.selected_vertices_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_vertices", ".bin");
            result.selected_edges_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_edges", ".bin");
            result.selected_faces_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_faces", ".bin");
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::vector<SubmeshSelectionPreviewResult> mesh_editor_selection_preview_report_items(
    const MeshEditorSession& session,
    const std::string& output_dir,
    const std::string& session_id
) {
    std::set<int> targets = session.selection.source_indices;
    for (const auto& mapping : {session.selection.vertices, session.selection.faces}) {
        for (const auto& entry : mapping) {
            targets.insert(entry.first);
        }
    }
    for (const auto& entry : session.selection.edges) {
        targets.insert(entry.first);
    }

    std::vector<SubmeshSelectionPreviewResult> results;
    for (const int submesh_index : targets) {
        const auto submesh_found = session.submeshes.find(submesh_index);
        if (submesh_found == session.submeshes.end()) {
            continue;
        }
        const MeshSessionSubmesh& submesh = submesh_found->second;
        const std::size_t vertex_count = submesh.vertices.size();
        if (vertex_count == 0) {
            continue;
        }
        std::set<int> source_vertices;
        std::set<std::array<int, 2>> source_edges;
        std::set<int> source_faces;

        if (session.selection.source_indices.find(submesh_index) != session.selection.source_indices.end()) {
            for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
                source_vertices.insert(static_cast<int>(vertex_index));
            }
        }
        const auto vertices = session.selection.vertices.find(submesh_index);
        if (vertices != session.selection.vertices.end()) {
            for (const int vertex_index : vertices->second) {
                if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < vertex_count) {
                    source_vertices.insert(vertex_index);
                }
            }
        }
        const std::set<std::array<int, 2>> existing_edges = face_edge_set(submesh.faces);
        const auto edges = session.selection.edges.find(submesh_index);
        if (edges != session.selection.edges.end()) {
            for (const auto& edge : edges->second) {
                if (edge[0] < 0 || edge[1] < 0
                    || static_cast<std::size_t>(edge[0]) >= vertex_count
                    || static_cast<std::size_t>(edge[1]) >= vertex_count
                    || edge[0] == edge[1]) {
                    continue;
                }
                if (!submesh.faces.empty() && existing_edges.find(edge) == existing_edges.end()) {
                    continue;
                }
                source_edges.insert(edge);
                source_vertices.insert(edge[0]);
                source_vertices.insert(edge[1]);
            }
        }
        const auto faces = session.selection.faces.find(submesh_index);
        if (faces != session.selection.faces.end()) {
            for (const int face_index : faces->second) {
                if (face_index < 0 || static_cast<std::size_t>(face_index) >= submesh.faces.size()) {
                    continue;
                }
                source_faces.insert(face_index);
                const auto& face = submesh.faces[static_cast<std::size_t>(face_index)];
                source_vertices.insert(face[0]);
                source_vertices.insert(face[1]);
                source_vertices.insert(face[2]);
            }
        }
        if (source_vertices.empty()) {
            continue;
        }
        SubmeshSelectionPreviewResult result;
        result.index = submesh_index;
        result.source_vertex_indices.assign(source_vertices.begin(), source_vertices.end());
        result.source_edges.assign(source_edges.begin(), source_edges.end());
        result.source_face_indices.assign(source_faces.begin(), source_faces.end());
        if (!output_dir.empty()) {
            result.selection_preview_path = mesh_editor_delta_path(output_dir, session_id, submesh_index, "selection_preview", ".bin");
        }
        results.push_back(std::move(result));
    }
    return results;
}

std::string mesh_editor_select_report_json(
    const MeshEditorSession& session,
    const std::string& session_id,
    const std::string& selection_operation,
    const std::string& output_dir,
    double cpp_ms,
    int source_pick_count = -1
) {
    const std::vector<SubmeshSelectionPruneResult> results = mesh_editor_selection_report_items(session.selection, output_dir, session_id);
    const std::vector<SubmeshSelectionPreviewResult> selection_groups =
        mesh_editor_selection_preview_report_items(session, output_dir, session_id);
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"select\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"selection_operation\":";
    write_escaped(out, selection_operation);
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    std::size_t selected_vertex_count = 0;
    std::size_t selected_edge_count = 0;
    std::size_t selected_face_count = 0;
    for (const auto& entry : session.submeshes) {
        vertex_count += entry.second.vertices.size();
        face_count += entry.second.faces.size();
    }
    for (const auto& entry : session.selection.vertices) {
        selected_vertex_count += entry.second.size();
    }
    for (const auto& entry : session.selection.edges) {
        selected_edge_count += entry.second.size();
    }
    for (const auto& entry : session.selection.faces) {
        selected_face_count += entry.second.size();
    }
    out << ",\"submesh_count\":" << session.submeshes.size()
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"topology_revision\":" << session.topology_revision
        << ",\"selection_revision\":" << session.selection_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"stroke_revision\":" << session.stroke_revision
        << ",\"active_stroke\":" << (session.active_stroke.active ? "true" : "false")
        << ",\"selected_vertex_count\":" << selected_vertex_count
        << ",\"selected_edge_count\":" << selected_edge_count
        << ",\"selected_face_count\":" << selected_face_count;
    out << ",\"source_indices\":";
    write_int_vector(out, std::vector<int>(session.selection.source_indices.begin(), session.selection.source_indices.end()));
    if (source_pick_count >= 0) {
        out << ",\"source_pick_count\":" << source_pick_count;
    }
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_prune_item(out, results[i]);
    }
    out << "],\"selection_groups\":[";
    for (std::size_t i = 0; i < selection_groups.size(); ++i) {
        if (i) {
            out << ',';
        }
        write_selection_preview_group(out, selection_groups[i]);
    }
    out << "],";
    write_command_metrics(out, cpp_ms);
    out << "}";
    return out.str();
}

void write_changed_vertices_report(
    std::ostream& out,
    const std::vector<int>& changed_vertices,
    const std::string& changed_vertices_path,
    int& changed_vertex_start
) {
    changed_vertex_start = -1;
    if (changed_vertices.empty()) {
        out << ",\"changed_vertex_start\":0,\"changed_vertex_count\":0";
        return;
    }
    if (contiguous_int_range(changed_vertices, changed_vertex_start)) {
        out << ",\"changed_vertex_start\":" << changed_vertex_start
            << ",\"changed_vertex_count\":" << changed_vertices.size();
        return;
    }
    changed_vertex_start = -1;
    if (!changed_vertices_path.empty()) {
        write_int_binary_file(changed_vertices_path, changed_vertices);
        out << ",\"changed_vertices_binary\":";
        write_int_binary_descriptor(out, changed_vertices_path, changed_vertices.size(), 1);
        return;
    }
    out << ",\"changed_vertices\":";
    write_int_vector(out, changed_vertices);
}

std::string transform_report_json(const std::vector<SubmeshTransformResult>& results, const std::string& operation = "transform") {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshTransformResult& result = results[i];
        out << "{\"index\":" << result.index;
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.before_positions.empty() && !result.before_positions_path.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            write_vec3_binary_file(result.before_positions_path, result.before_positions);
            out << ",\"before_positions_binary\":";
            write_vec3_binary_descriptor(out, result.before_positions_path, result.before_positions.size());
        }
        if (!result.sparse_snapshot_id.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            out << ",\"native_sparse_snapshot_id\":";
            write_escaped(out, result.sparse_snapshot_id);
        }
        if (result.sparse) {
            if (!result.changed_positions_path.empty()) {
                write_vec3_binary_file(result.changed_positions_path, result.changed_positions);
                out << ",\"changed_positions_binary\":";
                write_vec3_binary_descriptor(out, result.changed_positions_path, result.changed_positions.size());
            } else {
                out << ",\"changed_positions\":[";
                for (std::size_t j = 0; j < result.changed_positions.size(); ++j) {
                    if (j) {
                        out << ',';
                    }
                    write_vec3(out, result.changed_positions[j]);
                }
                out << "]";
            }
        } else {
            out << ",\"vertices\":[";
            for (std::size_t j = 0; j < result.vertices.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.vertices[j]);
            }
            out << "]";
        }
        out << ",\"preview_vertex_update_group\":";
        if (result.sparse) {
            write_sparse_preview_vertex_update_group(
                out,
                result.index,
                result.changed_vertices,
                result.changed_positions,
                {},
                {},
                result.changed_positions_path,
                changed_vertex_start,
                result.source_vertex_map
            );
        } else {
            write_preview_vertex_update_group(
                out,
                result.index,
                result.changed_vertices,
                result.vertices,
                {},
                {},
                result.changed_vertices_path,
                result.source_vertex_map
            );
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string uv_transform_report_json(const std::vector<SubmeshUvTransformResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"uv_transform\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshUvTransformResult& result = results[i];
        out << "{\"index\":" << result.index;
        if (result.status != "ok") {
            out << ",\"status\":";
            write_escaped(out, result.status);
            if (!result.error.empty()) {
                out << ",\"error\":";
                write_escaped(out, result.error);
            }
            out << ",\"invalid_vertex_index\":" << result.invalid_vertex_index
                << ",\"invalid_uv\":";
            write_vec2(out, result.invalid_uv);
            out << "}";
            continue;
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (result.clear_uvs) {
            out << ",\"clear_uvs\":true}";
            continue;
        }
        if (!result.uvs_path.empty()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        } else {
            out << ",\"uvs\":[";
            for (std::size_t j = 0; j < result.uvs.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec2(out, result.uvs[j]);
            }
            out << ']';
        }
        if (!result.changed_vertices.empty() && result.vertices.size() == result.uvs.size()) {
            std::vector<Vec3> changed_positions;
            changed_positions.reserve(result.changed_vertices.size());
            for (const int vertex_index : result.changed_vertices) {
                if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= result.vertices.size()) {
                    changed_positions.clear();
                    break;
                }
                changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
            }
            if (changed_positions.size() == result.changed_vertices.size()) {
                out << ",\"preview_vertex_update_group\":";
                write_sparse_preview_vertex_update_group(
                    out,
                    result.index,
                    result.changed_vertices,
                    changed_positions,
                    result.normals,
                    result.uvs,
                    result.preview_vertex_path,
                    changed_vertex_start
                );
            }
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string auto_uv_report_json(const std::vector<SubmeshAutoUvResult>& results) {
    std::ostringstream out;
    bool topology_changed = false;
    for (const SubmeshAutoUvResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"auto_uv\",\"unwrap_backend\":\"xatlas\",\"topology_changed\":" << (topology_changed ? "true" : "false") << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshAutoUvResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"status\":";
        write_escaped(out, result.status);
        out << ",\"unwrap_backend\":\"xatlas\""
            << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
            << ",\"input_vertex_count\":" << result.input_vertex_count
            << ",\"output_vertex_count\":" << result.output_vertex_count
            << ",\"input_face_count\":" << result.input_face_count
            << ",\"output_face_count\":" << result.output_face_count
            << ",\"chart_count\":" << result.chart_count;
        if (!result.error.empty()) {
            out << ",\"error\":";
            write_escaped(out, result.error);
        }
        if (!result.vertex_remap_path.empty()) {
            write_int_binary_file(result.vertex_remap_path, result.vertex_remap);
            out << ",\"vertex_remap_binary\":";
            write_int_binary_descriptor(out, result.vertex_remap_path, result.vertex_remap.size(), 1);
        } else {
            out << ",\"vertex_remap\":[";
            for (std::size_t j = 0; j < result.vertex_remap.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << result.vertex_remap[j];
            }
            out << ']';
        }
        if (!result.faces_path.empty()) {
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        } else {
            out << ",\"faces\":[";
            for (std::size_t j = 0; j < result.faces.size(); ++j) {
                if (j) {
                    out << ',';
                }
                out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
            }
            out << ']';
        }
        if (!result.uvs_path.empty()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        } else {
            out << ",\"uvs\":[";
            for (std::size_t j = 0; j < result.uvs.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec2(out, result.uvs[j]);
            }
            out << ']';
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.vertices_path.empty() && result.vertices.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.tangents_path.empty() && result.tangents.size() == result.vertex_remap.size()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        }
        if (!result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertex_remap.size()) {
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
        }
        const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
        if (!result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && bone_counts.size() == result.vertex_remap.size()) {
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(result.bone_counts_path, bone_counts);
                write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
            }
        }
        if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertex_remap.size()) {
            write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
            out << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
        }
        if (!result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertex_remap.size()) {
            write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
            out << ",\"source_vertex_offsets_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string normals_report_json(const std::vector<SubmeshNormalsResult>& results, const std::string& operation) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshNormalsResult& result = results[i];
        out << "{\"index\":" << result.index;
        if (!result.normals_path.empty()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        } else {
            out << ",\"normals\":[";
            for (std::size_t j = 0; j < result.normals.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.normals[j]);
            }
            out << ']';
        }
        if (!result.faces.empty()) {
            if (!result.faces_path.empty()) {
                std::vector<int> flat_faces;
                flat_faces.reserve(result.faces.size() * 3);
                for (const std::array<int, 3>& face : result.faces) {
                    flat_faces.push_back(face[0]);
                    flat_faces.push_back(face[1]);
                    flat_faces.push_back(face[2]);
                }
                write_int_binary_file(result.faces_path, flat_faces);
                out << ",\"faces_binary\":";
                write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
            } else {
                out << ",\"faces\":[";
                for (std::size_t j = 0; j < result.faces.size(); ++j) {
                    if (j) {
                        out << ',';
                    }
                    out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
                }
                out << ']';
            }
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.changed_vertices.empty()) {
            if (operation != "flip_normals") {
                out << ",\"preview_vertex_update_group\":";
                std::vector<Vec3> changed_positions;
                changed_positions.reserve(result.changed_vertices.size());
                for (const int vertex_index : result.changed_vertices) {
                    if (vertex_index < 0 || static_cast<std::size_t>(vertex_index) >= result.vertices.size()) {
                        changed_positions.clear();
                        break;
                    }
                    changed_positions.push_back(result.vertices[static_cast<std::size_t>(vertex_index)]);
                }
                if (!result.preview_vertex_path.empty() && changed_positions.size() == result.changed_vertices.size()) {
                    write_vec3_binary_file(result.preview_vertex_path, changed_positions);
                    write_sparse_preview_vertex_update_group(
                        out,
                        result.index,
                        result.changed_vertices,
                        changed_positions,
                        result.normals,
                        result.uvs,
                        result.preview_vertex_path,
                        changed_vertex_start,
                        result.source_vertex_map
                    );
                } else {
                    write_preview_vertex_update_group(
                        out,
                        result.index,
                        result.changed_vertices,
                        result.vertices,
                        result.normals,
                        result.uvs,
                        result.changed_vertices_path,
                        result.source_vertex_map
                    );
                }
            }
        }
        if (operation == "flip_normals" && !result.vertices.empty() && !result.faces.empty()) {
            out << ",\"preview_triangle_group\":";
            write_preview_triangle_group(
                out,
                result.index,
                result.vertices,
                result.faces,
                result.normals,
                result.uvs,
                result.preview_triangle_path,
                result.source_vertex_map
            );
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string tangents_report_json(const std::vector<SubmeshTangentsResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"generate_tangents\",\"tangent_backend\":";
    write_escaped(out, tangent_backend_summary(results));
    out << ",\"remap\":\"vertex_average_after_face_corner_output\",\"face_corner_remap\":\"face_corner_tangents_reported_vertex_storage_averaged\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshTangentsResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"tangent_backend\":";
        write_escaped(out, result.tangent_backend);
        out << ",\"face_corner_remap\":\"mikktspace_face_corner_tangents_reported_vertex_storage_averaged\""
            << ",\"face_corner_tangent_count\":" << result.face_corner_tangent_count
            << ",\"degenerate_uv_faces\":" << result.degenerate_uv_faces
            << ",\"vertex_storage_safe\":" << (result.vertex_storage_safe ? "true" : "false")
            << ",\"split_required_vertices\":[";
        for (std::size_t j = 0; j < result.split_required_vertices.size(); ++j) {
            if (j) {
                out << ',';
            }
            out << result.split_required_vertices[j];
        }
        out << ']';
        if (result.clear_tangents) {
            out << ",\"clear_tangents\":true";
            int changed_vertex_start = -1;
            write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
            out << "}";
            continue;
        }
        if (result.topology_split_applied) {
            out << ",\"topology_split_applied\":true"
                << ",\"output_vertex_count\":" << result.vertices.size()
                << ",\"output_face_count\":" << result.faces.size();
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
            const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
            if (!result.bone_counts_path.empty()
                && !result.bone_indices_path.empty()
                && !result.bone_weights_path.empty()
                && bone_counts.size() == result.vertices.size()) {
                const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
                const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
                if (flat_bone_indices.size() == flat_bone_weights.size()) {
                    write_int_binary_file(result.bone_counts_path, bone_counts);
                    write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                    write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                    out << ",\"bone_counts_binary\":";
                    write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                    out << ",\"bone_indices_binary\":";
                    write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                    out << ",\"bone_weights_binary\":";
                    write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
                }
            }
            if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
                write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
                out << ",\"source_vertex_map_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
            }
            if (!result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertices.size()) {
                write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
                out << ",\"source_vertex_offsets_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
            }
        }
        if (!result.vertex_storage_safe && !result.topology_split_applied) {
            out << ",\"face_corner_tangents\":[";
            for (std::size_t j = 0; j < result.face_corner_tangents.size(); ++j) {
                if (j) {
                    out << ',';
                }
                const FaceCornerTangents& face_corners = result.face_corner_tangents[j];
                out << "{\"face_index\":" << face_corners.face_index << ",\"vertices\":[";
                for (std::size_t k = 0; k < face_corners.vertices.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    out << face_corners.vertices[k];
                }
                out << "],\"tangents\":[";
                for (std::size_t k = 0; k < face_corners.tangents.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    write_vec3(out, face_corners.tangents[k]);
                }
                out << "],\"signs\":[";
                for (std::size_t k = 0; k < face_corners.signs.size(); ++k) {
                    if (k) {
                        out << ',';
                    }
                    out << face_corners.signs[k];
                }
                out << "]}";
            }
            out << ']';
        }
        if (!result.tangents_path.empty()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        } else {
            out << ",\"tangents\":[";
            for (std::size_t j = 0; j < result.tangents.size(); ++j) {
                if (j) {
                    out << ',';
                }
                write_vec3(out, result.tangents[j]);
            }
            out << ']';
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        out << "}";
    }
    out << "]}";
    return out.str();
}

std::string cleanup_report_json(const std::vector<SubmeshCleanupResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshCleanupResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"removed_vertices\":" << result.removed_vertices
            << ",\"removed_faces\":" << result.removed_faces
            << ",\"merged_vertices\":" << result.merged_vertices
            << ",\"degenerate_faces\":" << result.degenerate_faces
            << ",\"duplicate_faces\":" << result.duplicate_faces;
        if (result.suppress_index_map_report) {
            out << ",\"index_map_report_suppressed\":true";
        } else if (!result.index_map_path.empty()) {
            write_int_binary_file(result.index_map_path, result.index_map);
            out << ",\"index_map_binary\":";
            write_int_binary_descriptor(out, result.index_map_path, result.index_map.size(), 1);
        } else {
            out << ",\"index_map\":[";
            for (std::size_t j = 0; j < result.index_map.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << result.index_map[j];
            }
            out << ']';
        }
        if (!result.vertices_path.empty()) {
            write_vec3_binary_file(result.vertices_path, result.vertices);
            out << ",\"vertices_binary\":";
            write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
        } else {
            out << ",\"vertices\":[";
            for (std::size_t j = 0; j < result.vertices.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                write_vec3(out, result.vertices[j]);
            }
            out << ']';
        }
        if (!result.faces_path.empty()) {
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        } else {
            out << ",\"faces\":[";
            for (std::size_t j = 0; j < result.faces.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
            }
            out << ']';
        }
        if (!result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (!result.uvs_path.empty() && result.uvs.size() == result.vertices.size()) {
            write_vec2_binary_file(result.uvs_path, result.uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size());
        }
        if (!result.tangents_path.empty() && result.tangents.size() == result.vertices.size()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        }
        if (!result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertices.size()) {
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
        }
        const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
        if (!result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && bone_counts.size() == result.vertices.size()) {
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(result.bone_counts_path, bone_counts);
                write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
            }
        }
        if (!result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
            write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
            out << ",\"source_vertex_map_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
        }
        if (!result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertices.size()) {
            write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
            out << ",\"source_vertex_offsets_binary\":";
            write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string mesh_edit_report_json(const std::vector<SubmeshMeshEditResult>& results, bool include_preview_deltas = true) {
    std::ostringstream out;
    bool topology_changed = false;
    std::string operation = "edit";
    for (const SubmeshMeshEditResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
        if (operation == "edit" && !result.action.empty()) {
            operation = result.action;
        }
    }
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, operation);
    out << ",\"topology_changed\":" << (topology_changed ? "true" : "false") << ",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshMeshEditResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"action\":";
        write_escaped(out, result.action);
        if (result.append_submesh) {
            out << ",\"append_submesh\":true"
                << ",\"source_index\":" << result.source_index
                << ",\"name_suffix\":";
            write_escaped(out, result.name_suffix);
        }
        if (result.append_submesh || result.material_metadata_changed) {
            out << ",\"name\":";
            write_escaped(out, result.name);
            out << ",\"material\":";
            write_escaped(out, result.material);
            out << ",\"texture\":";
            write_escaped(out, result.texture);
            out << ",\"extra_attrs\":";
            if (result.extra_attrs.type == JsonValue::Type::Object) {
                write_json_value(out, result.extra_attrs);
            } else {
                out << "{}";
            }
        }
        out << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
            << ",\"removed_faces\":" << result.removed_faces
            << ",\"removed_vertices\":" << result.removed_vertices
            << ",\"added_vertices\":" << result.added_vertices
            << ",\"added_faces\":" << result.added_faces;
        if (result.suppress_vertex_remap_report) {
            out << ",\"vertex_remap_report_suppressed\":true";
        }
        int changed_vertex_start = -1;
        write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start);
        if (!result.before_positions.empty() && !result.before_positions_path.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            write_vec3_binary_file(result.before_positions_path, result.before_positions);
            out << ",\"before_positions_binary\":";
            write_vec3_binary_descriptor(out, result.before_positions_path, result.before_positions.size());
        }
        if (!result.sparse_snapshot_id.empty() && result.before_positions.size() == result.changed_vertices.size()) {
            out << ",\"native_sparse_snapshot_id\":";
            write_escaped(out, result.sparse_snapshot_id);
        }
        if (result.sparse && !result.topology_changed) {
            if (!result.changed_positions_path.empty()) {
                write_vec3_binary_file(result.changed_positions_path, result.changed_positions);
                out << ",\"changed_positions_binary\":";
                write_vec3_binary_descriptor(out, result.changed_positions_path, result.changed_positions.size());
            } else {
                out << ",\"changed_positions\":[";
                for (std::size_t j = 0; j < result.changed_positions.size(); ++j) {
                    if (j > 0) {
                        out << ',';
                    }
                    write_vec3(out, result.changed_positions[j]);
                }
                out << ']';
            }
        } else {
            if (!result.vertices_path.empty()) {
                write_vec3_binary_file(result.vertices_path, result.vertices);
                out << ",\"vertices_binary\":";
                write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size());
            } else {
                out << ",\"vertices\":[";
                for (std::size_t j = 0; j < result.vertices.size(); ++j) {
                    if (j > 0) {
                        out << ',';
                    }
                    write_vec3(out, result.vertices[j]);
                }
                out << ']';
            }
        }
        if (!result.faces_path.empty()) {
            write_faces_binary_file(result.faces_path, result.faces);
            out << ",\"faces_binary\":";
            write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3);
        } else {
            out << ",\"faces\":[";
            for (std::size_t j = 0; j < result.faces.size(); ++j) {
                if (j > 0) {
                    out << ',';
                }
                out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
            }
            out << ']';
        }
        if (!result.uvs_path.empty() && result.preview_uvs.size() == result.vertices.size()) {
            write_vec2_binary_file(result.uvs_path, result.preview_uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, result.uvs_path, result.preview_uvs.size());
        }
        if (result.topology_changed && !result.normals_path.empty() && result.normals.size() == result.vertices.size()) {
            write_vec3_binary_file(result.normals_path, result.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, result.normals_path, result.normals.size());
        }
        if (result.topology_changed && !result.tangents_path.empty() && result.tangents.size() == result.vertices.size()) {
            write_vec3_binary_file(result.tangents_path, result.tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size());
        }
        if (result.topology_changed && !result.tangent_signs_path.empty() && result.tangent_signs.size() == result.vertices.size()) {
            write_double_binary_file(result.tangent_signs_path, result.tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, result.tangent_signs_path, result.tangent_signs.size());
        }
        const std::vector<int> bone_counts = bone_assignment_counts(result.bones);
        if (result.topology_changed
            && !result.bone_counts_path.empty()
            && !result.bone_indices_path.empty()
            && !result.bone_weights_path.empty()
            && bone_counts.size() == result.vertices.size()) {
            const std::vector<int> flat_bone_indices = flatten_bone_indices(result.bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(result.bones);
            if (flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(result.bone_counts_path, bone_counts);
                write_int_binary_file(result.bone_indices_path, flat_bone_indices);
                write_double_binary_file(result.bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, result.bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, result.bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, result.bone_weights_path, flat_bone_weights.size());
            }
        }
        if (result.topology_changed && !result.source_vertex_map_path.empty() && result.source_vertex_map.size() == result.vertices.size()) {
            int source_vertex_map_start = -1;
            if (contiguous_int_range(result.source_vertex_map, source_vertex_map_start)) {
                out << ",\"source_vertex_map_start\":" << source_vertex_map_start
                    << ",\"source_vertex_map_count\":" << result.source_vertex_map.size();
            } else {
                write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map);
                out << ",\"source_vertex_map_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_map_path, result.source_vertex_map.size(), 1);
            }
        }
        if (result.topology_changed && !result.source_vertex_offsets_path.empty() && result.source_vertex_offsets.size() == result.vertices.size()) {
            int source_vertex_offsets_start = -1;
            int source_vertex_offsets_stride = 0;
            if (contiguous_int_stride_range(result.source_vertex_offsets, source_vertex_offsets_start, source_vertex_offsets_stride)) {
                out << ",\"source_vertex_offsets_start\":" << source_vertex_offsets_start
                    << ",\"source_vertex_offsets_count\":" << result.source_vertex_offsets.size()
                    << ",\"source_vertex_offsets_stride\":" << source_vertex_offsets_stride;
            } else {
                write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets);
                out << ",\"source_vertex_offsets_binary\":";
                write_int_binary_descriptor(out, result.source_vertex_offsets_path, result.source_vertex_offsets.size(), 1);
            }
        }
        if (!result.suppress_vertex_remap_report) {
            if (!result.copy_vertex_indices_path.empty()) {
                write_int_binary_file(result.copy_vertex_indices_path, result.copy_vertex_indices);
                out << ",\"copy_vertex_indices_binary\":";
                write_int_binary_descriptor(out, result.copy_vertex_indices_path, result.copy_vertex_indices.size(), 1);
            } else {
                out << ",\"copy_vertex_indices\":[";
                for (std::size_t j = 0; j < result.copy_vertex_indices.size(); ++j) {
                    if (j > 0) {
                        out << ',';
                    }
                    out << result.copy_vertex_indices[j];
                }
                out << ']';
            }
            if (!result.vertex_blend_indices_path.empty() && !result.vertex_blend_factors_path.empty()) {
                write_int_binary_file(result.vertex_blend_indices_path, flatten_vertex_blend_indices(result.vertex_blends));
                write_double_binary_file(result.vertex_blend_factors_path, flatten_vertex_blend_factors(result.vertex_blends));
                out << ",\"vertex_blend_indices_binary\":";
                write_int_binary_descriptor(out, result.vertex_blend_indices_path, result.vertex_blends.size(), 3);
                out << ",\"vertex_blend_factors_binary\":";
                write_f64_binary_descriptor(out, result.vertex_blend_factors_path, result.vertex_blends.size());
            } else {
                out << ",\"vertex_blends\":[";
                for (std::size_t j = 0; j < result.vertex_blends.size(); ++j) {
                    if (j > 0) {
                        out << ',';
                    }
                    const VertexBlend& blend = result.vertex_blends[j];
                    out << "{\"index\":" << blend.index
                        << ",\"left\":" << blend.left
                        << ",\"right\":" << blend.right
                        << ",\"factor\":" << std::setprecision(17) << blend.factor
                        << '}';
                }
                out << ']';
            }
            if (!result.index_map_path.empty()) {
                write_int_binary_file(result.index_map_path, result.index_map);
                out << ",\"index_map_binary\":";
                write_int_binary_descriptor(out, result.index_map_path, result.index_map.size(), 1);
            } else {
                out << ",\"index_map\":[";
                for (std::size_t j = 0; j < result.index_map.size(); ++j) {
                    if (j > 0) {
                        out << ',';
                    }
                    out << result.index_map[j];
                }
                out << ']';
            }
        }
        if (include_preview_deltas && !result.topology_changed && !result.changed_vertices.empty()) {
            out << ",\"preview_vertex_update_group\":";
            if (result.sparse) {
                write_sparse_preview_vertex_update_group(
                    out,
                    result.index,
                    result.changed_vertices,
                    result.changed_positions,
                    result.preview_normals,
                    result.preview_uvs,
                    result.changed_positions_path,
                    changed_vertex_start,
                    result.source_vertex_map
                );
            } else {
                write_preview_vertex_update_group(
                    out,
                    result.index,
                    result.changed_vertices,
                    result.vertices,
                    result.preview_normals,
                    result.preview_uvs,
                    result.changed_vertices_path,
                    result.source_vertex_map
                );
            }
        }
        if (include_preview_deltas && (result.topology_changed || result.material_metadata_changed || !result.faces.empty())) {
            const bool has_triangles = !result.vertices.empty() && !result.faces.empty();
            const std::vector<Vec3> preview_normals = has_triangles
                ? compute_smooth_normals(result.vertices, result.faces)
                : std::vector<Vec3>();
            out << ",\"preview_triangle_group\":";
            write_preview_triangle_group(
                out,
                result.index,
                result.vertices,
                result.faces,
                preview_normals,
                result.preview_uvs,
                result.preview_triangle_path,
                result.source_vertex_map,
                result.source_face_indices
            );
        }
        out << "}";
    }
    out << "]}";
    return out.str();
}

void write_optimization_stats(std::ostream& out, const OptimizationStats& stats) {
    out << "{\"cache_acmr\":" << std::setprecision(17) << stats.cache_acmr
        << ",\"cache_atvr\":" << stats.cache_atvr
        << ",\"overdraw\":" << stats.overdraw
        << ",\"overfetch\":" << stats.overfetch
        << '}';
}

std::string optimize_report_json(const std::vector<SubmeshOptimizeResult>& results) {
    std::ostringstream out;
    bool topology_changed = false;
    int input_indices = 0;
    int output_indices = 0;
    int input_triangles = 0;
    int output_triangles = 0;
    int input_vertices = 0;
    int referenced_vertices = 0;
    for (const SubmeshOptimizeResult& result : results) {
        topology_changed = topology_changed || result.topology_changed;
        input_indices += result.input_index_count;
        output_indices += result.output_index_count;
        input_triangles += result.input_triangle_count;
        output_triangles += result.output_triangle_count;
        input_vertices += result.input_vertex_count;
        referenced_vertices += result.referenced_vertex_count;
    }

    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"optimize\",\"optimization_backend\":\"meshoptimizer\""
        << ",\"topology_changed\":" << (topology_changed ? "true" : "false")
        << ",\"totals\":{\"input_vertex_count\":" << input_vertices
        << ",\"referenced_vertex_count\":" << referenced_vertices
        << ",\"input_index_count\":" << input_indices
        << ",\"output_index_count\":" << output_indices
        << ",\"input_triangle_count\":" << input_triangles
        << ",\"output_triangle_count\":" << output_triangles
        << "},\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const SubmeshOptimizeResult& result = results[i];
        out << "{\"index\":" << result.index
            << ",\"optimization_backend\":\"meshoptimizer\""
            << ",\"input_vertex_count\":" << result.input_vertex_count
            << ",\"referenced_vertex_count\":" << result.referenced_vertex_count
            << ",\"fetch_vertex_count\":" << result.fetch_vertex_count
            << ",\"input_index_count\":" << result.input_index_count
            << ",\"output_index_count\":" << result.output_index_count
            << ",\"input_triangle_count\":" << result.input_triangle_count
            << ",\"output_triangle_count\":" << result.output_triangle_count
            << ",\"target_ratio\":" << std::setprecision(17) << result.target_ratio
            << ",\"target_error\":" << result.target_error
            << ",\"result_error\":" << result.result_error
            << ",\"simplified\":" << (result.simplified ? "true" : "false")
            << ",\"topology_changed\":" << (result.topology_changed ? "true" : "false")
            << ",\"before\":";
        write_optimization_stats(out, result.before);
        out << ",\"after\":";
        write_optimization_stats(out, result.after);
        out << ",\"faces\":[";
        for (std::size_t j = 0; j < result.faces.size(); ++j) {
            if (j > 0) {
                out << ',';
            }
            out << '[' << result.faces[j][0] << ',' << result.faces[j][1] << ',' << result.faces[j][2] << ']';
        }
        out << "]}";
    }
    out << "]}";
    return out.str();
}

std::string error_report_json(const std::string& message) {
    std::ostringstream out;
    out << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":";
    write_escaped(out, message);
    out << '}';
    return out.str();
}

void append_i32_le(std::vector<char>& out, int value) {
    const std::int32_t raw = static_cast<std::int32_t>(value);
    out.push_back(static_cast<char>(raw & 0xff));
    out.push_back(static_cast<char>((raw >> 8) & 0xff));
    out.push_back(static_cast<char>((raw >> 16) & 0xff));
    out.push_back(static_cast<char>((raw >> 24) & 0xff));
}

std::string lower_ascii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

void append_f32_le(std::vector<char>& out, double value) {
    const float raw = static_cast<float>(std::isfinite(value) ? value : 0.0);
    std::uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(raw), "float size must be 32-bit");
    std::memcpy(&bits, &raw, sizeof(bits));
    out.push_back(static_cast<char>(bits & 0xffu));
    out.push_back(static_cast<char>((bits >> 8) & 0xffu));
    out.push_back(static_cast<char>((bits >> 16) & 0xffu));
    out.push_back(static_cast<char>((bits >> 24) & 0xffu));
}

Vec3 cross_vec3(const Vec3& left, const Vec3& right) {
    return {
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    };
}

Vec3 sanitize_normal_for_preview(const Vec3& value, bool* repaired = nullptr) {
    const double length = std::sqrt(dot_vec3(value, value));
    if (length > 1e-8 && std::isfinite(length)) {
        if (repaired != nullptr) {
            *repaired = false;
        }
        return {value[0] / length, value[1] / length, value[2] / length};
    }
    if (repaired != nullptr) {
        *repaired = true;
    }
    return {0.0, 0.0, 1.0};
}

void orthogonal_tangent_frame_for_preview(const Vec3& normal_value, Vec3& tangent, Vec3& bitangent) {
    Vec3 normal = sanitize_normal_for_preview(normal_value);
    const Vec3 seed = std::abs(normal[2]) < 0.999 ? Vec3{0.0, 0.0, 1.0} : Vec3{1.0, 0.0, 0.0};
    tangent = normalized_vec3(cross_vec3(seed, normal), {1.0, 0.0, 0.0});
    bitangent = normalized_vec3(cross_vec3(normal, tangent), {0.0, 1.0, 0.0});
}

std::vector<int> valid_triangle_indices_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::vector<int> result;
    const std::vector<int> indices = int_vector_from_json(value);
    result.reserve(indices.size());
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.push_back(a);
        result.push_back(b);
        result.push_back(c);
    }
    return result;
}

struct PreviewTriangleIndexStream {
    std::vector<int> flat_indices;
    std::vector<int> face_ordinals;
};

PreviewTriangleIndexStream preview_triangle_index_stream_from_json(const JsonValue* value, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    const std::vector<int> indices = int_vector_from_json(value);
    result.flat_indices.reserve(indices.size());
    result.face_ordinals.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(offset / 3));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_binary_or_json(const JsonValue& item, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    const std::vector<int> indices = int_vector_from_binary_or_json(item, "indices_binary", "indices");
    result.flat_indices.reserve(indices.size());
    result.face_ordinals.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        const int a = indices[offset];
        const int b = indices[offset + 1];
        const int c = indices[offset + 2];
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(offset / 3));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_faces_json(const JsonValue* value, std::size_t vertex_count) {
    PreviewTriangleIndexStream result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    result.flat_indices.reserve(value->array_value.size() * 3u);
    result.face_ordinals.reserve(value->array_value.size());
    for (std::size_t face_index = 0; face_index < value->array_value.size(); ++face_index) {
        const JsonValue& face = value->array_value[face_index];
        if (face.type != JsonValue::Type::Array || face.array_value.size() < 3) {
            continue;
        }
        const int a = int_or(&face.array_value[0], -1);
        const int b = int_or(&face.array_value[1], -1);
        const int c = int_or(&face.array_value[2], -1);
        if (a < 0 || b < 0 || c < 0
            || static_cast<std::size_t>(a) >= vertex_count
            || static_cast<std::size_t>(b) >= vertex_count
            || static_cast<std::size_t>(c) >= vertex_count) {
            continue;
        }
        result.flat_indices.push_back(a);
        result.flat_indices.push_back(b);
        result.flat_indices.push_back(c);
        result.face_ordinals.push_back(static_cast<int>(face_index));
    }
    return result;
}

PreviewTriangleIndexStream preview_triangle_index_stream_from_faces(const std::vector<std::array<int, 3>>& faces) {
    PreviewTriangleIndexStream result;
    result.flat_indices.reserve(faces.size() * 3u);
    result.face_ordinals.reserve(faces.size());
    for (std::size_t face_index = 0; face_index < faces.size(); ++face_index) {
        const std::array<int, 3>& face = faces[face_index];
        result.flat_indices.push_back(face[0]);
        result.flat_indices.push_back(face[1]);
        result.flat_indices.push_back(face[2]);
        result.face_ordinals.push_back(static_cast<int>(face_index));
    }
    return result;
}

std::vector<std::array<int, 3>> faces_from_flat_indices(const std::vector<int>& indices) {
    std::vector<std::array<int, 3>> faces;
    faces.reserve(indices.size() / 3);
    for (std::size_t offset = 0; offset + 2 < indices.size(); offset += 3) {
        faces.push_back({indices[offset], indices[offset + 1], indices[offset + 2]});
    }
    return faces;
}

struct PreviewSmoothNormalsResult {
    std::vector<Vec3> normals;
    double changed_ratio = 0.0;
};

std::array<long long, 3> preview_smooth_position_key(const Vec3& position) {
    return {
        static_cast<long long>(std::llround(position[0] * 100000.0)),
        static_cast<long long>(std::llround(position[1] * 100000.0)),
        static_cast<long long>(std::llround(position[2] * 100000.0)),
    };
}

PreviewSmoothNormalsResult build_preview_smoothed_normals(
    const std::vector<Vec3>& positions,
    const std::vector<Vec3>& normals,
    const std::vector<int>& flat_indices
) {
    PreviewSmoothNormalsResult result;
    result.normals = normals;
    const std::size_t vertex_count = positions.size();
    if (vertex_count == 0 || normals.size() != vertex_count) {
        return result;
    }
    std::map<std::array<long long, 3>, Vec3> accum_by_position;
    for (std::size_t offset = 0; offset + 2 < flat_indices.size(); offset += 3) {
        const int a = flat_indices[offset];
        const int b = flat_indices[offset + 1];
        const int c = flat_indices[offset + 2];
        const Vec3 ab = sub_vec3(positions[static_cast<std::size_t>(b)], positions[static_cast<std::size_t>(a)]);
        const Vec3 ac = sub_vec3(positions[static_cast<std::size_t>(c)], positions[static_cast<std::size_t>(a)]);
        const Vec3 face = cross_vec3(ab, ac);
        const double length = length_vec3(face);
        if (length <= 1e-12 || !std::isfinite(length)) {
            continue;
        }
        for (const int index : {a, b, c}) {
            Vec3& accum = accum_by_position[preview_smooth_position_key(positions[static_cast<std::size_t>(index)])];
            accum = add_vec3(accum, face);
        }
    }

    int changed = 0;
    for (std::size_t index = 0; index < vertex_count; ++index) {
        const Vec3 original = normals[index];
        const auto found = accum_by_position.find(preview_smooth_position_key(positions[index]));
        if (found == accum_by_position.end()) {
            result.normals[index] = original;
            continue;
        }
        bool repaired = false;
        const Vec3 candidate = sanitize_normal_for_preview(found->second, &repaired);
        if (repaired) {
            result.normals[index] = original;
            continue;
        }
        const double dot = dot_vec3(original, candidate);
        if (dot <= 0.05) {
            result.normals[index] = original;
            continue;
        }
        if (dot < 0.995) {
            ++changed;
        }
        result.normals[index] = candidate;
    }
    result.changed_ratio = static_cast<double>(changed) / static_cast<double>(std::max<std::size_t>(1, vertex_count));
    return result;
}

struct PreviewTangentFrames {
    std::vector<Vec3> tangents;
    std::vector<Vec3> bitangents;
    std::vector<bool> tangent_valid;
    std::vector<bool> bitangent_valid;
};

PreviewTangentFrames build_preview_tangent_frames(
    const std::vector<Vec3>& positions,
    const std::vector<Vec2>& uvs,
    const std::vector<Vec3>& normals,
    const std::vector<int>& flat_indices
) {
    const std::size_t vertex_count = positions.size();
    PreviewTangentFrames result;
    result.tangents.resize(vertex_count, {1.0, 0.0, 0.0});
    result.bitangents.resize(vertex_count, {0.0, 1.0, 0.0});
    result.tangent_valid.resize(vertex_count, false);
    result.bitangent_valid.resize(vertex_count, false);
    if (vertex_count == 0 || uvs.size() != vertex_count || normals.size() != vertex_count) {
        for (std::size_t index = 0; index < vertex_count; ++index) {
            orthogonal_tangent_frame_for_preview(normals.size() == vertex_count ? normals[index] : Vec3{0.0, 0.0, 1.0}, result.tangents[index], result.bitangents[index]);
        }
        return result;
    }

    std::vector<Vec3> tangent_accum(vertex_count, {0.0, 0.0, 0.0});
    std::vector<Vec3> bitangent_accum(vertex_count, {0.0, 0.0, 0.0});
    for (std::size_t offset = 0; offset + 2 < flat_indices.size(); offset += 3) {
        const int a = flat_indices[offset];
        const int b = flat_indices[offset + 1];
        const int c = flat_indices[offset + 2];
        const Vec3 edge1 = sub_vec3(positions[static_cast<std::size_t>(b)], positions[static_cast<std::size_t>(a)]);
        const Vec3 edge2 = sub_vec3(positions[static_cast<std::size_t>(c)], positions[static_cast<std::size_t>(a)]);
        const Vec2 uv0 = uvs[static_cast<std::size_t>(a)];
        const Vec2 uv1 = uvs[static_cast<std::size_t>(b)];
        const Vec2 uv2 = uvs[static_cast<std::size_t>(c)];
        const double du1 = uv1[0] - uv0[0];
        const double dv1 = uv1[1] - uv0[1];
        const double du2 = uv2[0] - uv0[0];
        const double dv2 = uv2[1] - uv0[1];
        const double determinant = du1 * dv2 - dv1 * du2;
        if (std::abs(determinant) <= 1e-8 || !std::isfinite(determinant)) {
            continue;
        }
        const double reciprocal = 1.0 / determinant;
        const Vec3 tangent = {
            reciprocal * ((dv2 * edge1[0]) - (dv1 * edge2[0])),
            reciprocal * ((dv2 * edge1[1]) - (dv1 * edge2[1])),
            reciprocal * ((dv2 * edge1[2]) - (dv1 * edge2[2])),
        };
        const Vec3 bitangent = {
            reciprocal * ((-du2 * edge1[0]) + (du1 * edge2[0])),
            reciprocal * ((-du2 * edge1[1]) + (du1 * edge2[1])),
            reciprocal * ((-du2 * edge1[2]) + (du1 * edge2[2])),
        };
        const double tangent_length = length_vec3(tangent);
        const double bitangent_length = length_vec3(bitangent);
        if (tangent_length <= 1e-8 || bitangent_length <= 1e-8 || !std::isfinite(tangent_length) || !std::isfinite(bitangent_length)) {
            continue;
        }
        for (const int vertex_index : {a, b, c}) {
            const std::size_t target = static_cast<std::size_t>(vertex_index);
            tangent_accum[target] = add_vec3(tangent_accum[target], tangent);
            bitangent_accum[target] = add_vec3(bitangent_accum[target], bitangent);
            result.tangent_valid[target] = true;
            result.bitangent_valid[target] = true;
        }
    }

    for (std::size_t index = 0; index < vertex_count; ++index) {
        const Vec3 normal = normals[index];
        Vec3 tangent;
        Vec3 bitangent;
        orthogonal_tangent_frame_for_preview(normal, tangent, bitangent);
        double tangent_length = length_vec3(tangent_accum[index]);
        if (tangent_length <= 1e-6 || !std::isfinite(tangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.tangent_valid[index] = false;
            result.bitangent_valid[index] = false;
            continue;
        }
        Vec3 projected_tangent = scale_vec3(tangent_accum[index], 1.0 / tangent_length);
        projected_tangent = sub_vec3(projected_tangent, scale_vec3(normal, dot_vec3(normal, projected_tangent)));
        tangent_length = length_vec3(projected_tangent);
        if (tangent_length <= 1e-6 || !std::isfinite(tangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.tangent_valid[index] = false;
            result.bitangent_valid[index] = false;
            continue;
        }
        tangent = scale_vec3(projected_tangent, 1.0 / tangent_length);
        Vec3 raw_bitangent = bitangent_accum[index];
        if (dot_vec3(raw_bitangent, raw_bitangent) <= 1e-6) {
            raw_bitangent = cross_vec3(normal, tangent);
            result.bitangent_valid[index] = false;
        }
        const double raw_bitangent_length = length_vec3(raw_bitangent);
        if (raw_bitangent_length <= 1e-6 || !std::isfinite(raw_bitangent_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.bitangent_valid[index] = false;
            continue;
        }
        Vec3 cross_bitangent = cross_vec3(normal, tangent);
        const double cross_length = length_vec3(cross_bitangent);
        if (cross_length <= 1e-6 || !std::isfinite(cross_length)) {
            result.tangents[index] = tangent;
            result.bitangents[index] = bitangent;
            result.bitangent_valid[index] = false;
            continue;
        }
        cross_bitangent = scale_vec3(cross_bitangent, 1.0 / cross_length);
        const double handedness = dot_vec3(cross_bitangent, raw_bitangent) < 0.0 ? -1.0 : 1.0;
        result.tangents[index] = tangent;
        result.bitangents[index] = scale_vec3(cross_bitangent, handedness);
    }
    return result;
}

int count_false_values(const std::vector<bool>& values) {
    int count = 0;
    for (bool value : values) {
        if (!value) {
            ++count;
        }
    }
    return count;
}

struct PreviewGeometryBatchReport {
    int mesh_index = -1;
    int first_vertex = 0;
    int vertex_count = 0;
    Vec3 bounds_min{0.0, 0.0, 0.0};
    Vec3 bounds_max{0.0, 0.0, 0.0};
    Vec3 base_color{1.0, 1.0, 1.0};
    bool has_texture_coordinates = false;
    bool texture_wrap_repeat = false;
    bool tangents_usable = false;
    double normal_finite_ratio = 1.0;
    int normal_repair_count = 0;
    double tangent_finite_ratio = 1.0;
    double bitangent_finite_ratio = 1.0;
    double uv_finite_ratio = 0.0;
    double smooth_normal_ratio = 0.0;
    double position_y_min = 0.0;
    double position_y_max = 0.0;
    std::vector<int> source_vertex_indices;
    std::vector<int> source_face_indices;
    int identity_offset = 0;
    int identity_size = 0;
};

struct PreviewModelMeshReport {
    int parsed_submesh_index = -1;
    int source_submesh_index = -1;
    std::vector<Vec3> positions;
    std::vector<Vec2> uvs;
    std::vector<Vec3> normals;
    std::vector<int> indices;
    std::vector<int> source_vertex_indices;
    std::vector<int> source_face_indices;
    std::string positions_path;
    std::string uvs_path;
    std::string normals_path;
    std::string indices_path;
    std::string source_vertex_indices_path;
    std::string source_face_indices_path;
};

bool finite_vec2(const Vec2& value) {
    return std::isfinite(value[0]) && std::isfinite(value[1]);
}

bool finite_vec3(const Vec3& value) {
    return std::isfinite(value[0]) && std::isfinite(value[1]) && std::isfinite(value[2]);
}

bool preview_vertex_tangent_usable(const Vec3& normal, const Vec2& uv, const Vec3& tangent, const Vec3& bitangent) {
    return finite_vec3(normal)
        && finite_vec2(uv)
        && finite_vec3(tangent)
        && finite_vec3(bitangent)
        && length_vec3(normal) > 0.05
        && length_vec3(tangent) > 0.05
        && length_vec3(bitangent) > 0.05;
}

void append_preview_vertex(
    std::vector<char>& geometry,
    const Vec3& position,
    const Vec3& normal,
    const Vec3& color,
    const Vec2& uv,
    const Vec3& tangent,
    const Vec3& bitangent,
    const Vec3& smooth_normal,
    const Vec3& barycentric
) {
    append_f32_le(geometry, position[0]);
    append_f32_le(geometry, position[1]);
    append_f32_le(geometry, position[2]);
    append_f32_le(geometry, normal[0]);
    append_f32_le(geometry, normal[1]);
    append_f32_le(geometry, normal[2]);
    append_f32_le(geometry, color[0]);
    append_f32_le(geometry, color[1]);
    append_f32_le(geometry, color[2]);
    append_f32_le(geometry, uv[0]);
    append_f32_le(geometry, uv[1]);
    append_f32_le(geometry, tangent[0]);
    append_f32_le(geometry, tangent[1]);
    append_f32_le(geometry, tangent[2]);
    append_f32_le(geometry, bitangent[0]);
    append_f32_le(geometry, bitangent[1]);
    append_f32_le(geometry, bitangent[2]);
    append_f32_le(geometry, smooth_normal[0]);
    append_f32_le(geometry, smooth_normal[1]);
    append_f32_le(geometry, smooth_normal[2]);
    append_f32_le(geometry, barycentric[0]);
    append_f32_le(geometry, barycentric[1]);
    append_f32_le(geometry, barycentric[2]);
}

std::string preview_geometry_report_json(
    const std::vector<PreviewGeometryBatchReport>& batches,
    int vertex_count,
    int geometry_size,
    const std::string& output_path = std::string()
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_geometry\""
        << ",\"vertex_stride_bytes\":92"
        << ",\"vertex_count\":" << vertex_count
        << ",\"geometry_size\":" << geometry_size
        << ",\"batches\":[";
    for (std::size_t i = 0; i < batches.size(); ++i) {
        if (i > 0) {
            out << ',';
        }
        const PreviewGeometryBatchReport& batch = batches[i];
        out << "{\"mesh_index\":" << batch.mesh_index
            << ",\"first_vertex\":" << batch.first_vertex
            << ",\"vertex_count\":" << batch.vertex_count
            << ",\"bounds_min\":";
        write_vec3(out, batch.bounds_min);
        out << ",\"bounds_max\":";
        write_vec3(out, batch.bounds_max);
        out << ",\"base_color\":";
        write_vec3(out, batch.base_color);
        out << ",\"tangents_usable\":" << (batch.tangents_usable ? "true" : "false")
            << ",\"has_texture_coordinates\":" << (batch.has_texture_coordinates ? "true" : "false")
            << ",\"texture_wrap_repeat\":" << (batch.texture_wrap_repeat ? "true" : "false")
            << ",\"normal_finite_ratio\":" << std::setprecision(17) << batch.normal_finite_ratio
            << ",\"normal_repair_count\":" << batch.normal_repair_count
            << ",\"tangent_finite_ratio\":" << batch.tangent_finite_ratio
            << ",\"bitangent_finite_ratio\":" << batch.bitangent_finite_ratio
            << ",\"uv_finite_ratio\":" << batch.uv_finite_ratio
            << ",\"smooth_normal_ratio\":" << batch.smooth_normal_ratio
            << ",\"position_y_min\":" << batch.position_y_min
            << ",\"position_y_max\":" << batch.position_y_max;
        int source_vertex_start = -1;
        if (contiguous_int_range(batch.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << batch.source_vertex_indices.size();
        } else if (!output_path.empty() && !batch.source_vertex_indices.empty()) {
            const std::string source_vertices_path = sibling_binary_path(
                output_path,
                ".batch_" + std::to_string(i) + ".source_vertices.bin");
            write_int_binary_file(source_vertices_path, batch.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_int_binary_descriptor(out, source_vertices_path, batch.source_vertex_indices.size(), 1);
        } else {
            out << ",\"source_vertex_indices\":";
            write_int_vector(out, batch.source_vertex_indices);
        }
        int source_face_start = -1;
        if (contiguous_int_range(batch.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << batch.source_face_indices.size();
        } else if (!output_path.empty() && !batch.source_face_indices.empty()) {
            const std::string source_faces_path = sibling_binary_path(
                output_path,
                ".batch_" + std::to_string(i) + ".source_faces.bin");
            write_int_binary_file(source_faces_path, batch.source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_int_binary_descriptor(out, source_faces_path, batch.source_face_indices.size(), 1);
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, batch.source_face_indices);
        }
        out << ",\"identity_offset\":" << batch.identity_offset
            << ",\"identity_size\":" << batch.identity_size
            << "}";
    }
    out << "]}";
    return out.str();
}

void write_vec3_vector(std::ostream& out, const std::vector<Vec3>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        write_vec3(out, values[index]);
    }
    out << ']';
}

void write_vec2_vector(std::ostream& out, const std::vector<Vec2>& values) {
    out << '[';
    for (std::size_t index = 0; index < values.size(); ++index) {
        if (index > 0) {
            out << ',';
        }
        write_vec2(out, values[index]);
    }
    out << ']';
}

std::string preview_model_report_json(
    const std::vector<PreviewModelMeshReport>& meshes,
    int vertex_count,
    int face_count
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_model\""
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"mesh_count\":" << meshes.size()
        << ",\"meshes\":[";
    for (std::size_t mesh_index = 0; mesh_index < meshes.size(); ++mesh_index) {
        if (mesh_index > 0) {
            out << ',';
        }
        const PreviewModelMeshReport& mesh = meshes[mesh_index];
        out << "{\"parsed_submesh_index\":" << mesh.parsed_submesh_index
            << ",\"source_submesh_index\":" << mesh.source_submesh_index
            << ",\"vertex_count\":" << mesh.positions.size()
            << ",\"face_count\":" << mesh.indices.size() / 3u;
        if (!mesh.positions_path.empty()) {
            write_vec3_binary_file(mesh.positions_path, mesh.positions);
            out << ",\"positions_binary\":";
            write_vec3_binary_descriptor(out, mesh.positions_path, mesh.positions.size());
        } else {
            out << ",\"positions\":";
            write_vec3_vector(out, mesh.positions);
        }
        if (!mesh.uvs_path.empty()) {
            write_vec2_binary_file(mesh.uvs_path, mesh.uvs);
            out << ",\"texture_coordinates_binary\":";
            write_vec2_binary_descriptor(out, mesh.uvs_path, mesh.uvs.size());
        } else {
            out << ",\"texture_coordinates\":";
            write_vec2_vector(out, mesh.uvs);
        }
        if (!mesh.normals_path.empty()) {
            write_vec3_binary_file(mesh.normals_path, mesh.normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, mesh.normals_path, mesh.normals.size());
        } else {
            out << ",\"normals\":";
            write_vec3_vector(out, mesh.normals);
        }
        if (!mesh.indices_path.empty()) {
            write_int_binary_file(mesh.indices_path, mesh.indices);
            out << ",\"indices_binary\":";
            write_int_binary_descriptor(out, mesh.indices_path, mesh.indices.size(), 1);
        } else {
            out << ",\"indices\":";
            write_int_vector(out, mesh.indices);
        }
        int source_vertex_start = -1;
        if (contiguous_int_range(mesh.source_vertex_indices, source_vertex_start)) {
            out << ",\"source_vertex_start\":" << source_vertex_start
                << ",\"source_vertex_count\":" << mesh.source_vertex_indices.size();
        } else if (!mesh.source_vertex_indices_path.empty()) {
            write_int_binary_file(mesh.source_vertex_indices_path, mesh.source_vertex_indices);
            out << ",\"source_vertex_indices_binary\":";
            write_int_binary_descriptor(out, mesh.source_vertex_indices_path, mesh.source_vertex_indices.size(), 1);
        } else {
            out << ",\"source_vertex_indices\":";
            write_int_vector(out, mesh.source_vertex_indices);
        }
        int source_face_start = -1;
        if (contiguous_int_range(mesh.source_face_indices, source_face_start)) {
            out << ",\"source_face_start\":" << source_face_start
                << ",\"source_face_count\":" << mesh.source_face_indices.size();
        } else if (!mesh.source_face_indices_path.empty()) {
            write_int_binary_file(mesh.source_face_indices_path, mesh.source_face_indices);
            out << ",\"source_face_indices_binary\":";
            write_int_binary_descriptor(out, mesh.source_face_indices_path, mesh.source_face_indices.size(), 1);
        } else {
            out << ",\"source_face_indices\":";
            write_int_vector(out, mesh.source_face_indices);
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}

std::string run_preview_model(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const Vec3 center = vec3_or(root.get("normalization_center"), {0.0, 0.0, 0.0});
    double scale = number_or(root.get("normalization_scale"), 1.0);
    if (std::abs(scale) <= 1e-12 || !std::isfinite(scale)) {
        scale = 1.0;
    }
    std::vector<PreviewModelMeshReport> reports;
    int vertex_count = 0;
    int face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int parsed_submesh_index = int_or(item.get("index"), -1);
        const int source_submesh_index = int_or(item.get("source_submesh_index"), parsed_submesh_index);
        std::vector<Vec3> vertices = mesh_vertices_from_item(item);
        if (parsed_submesh_index < 0 || vertices.empty()) {
            continue;
        }
        const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
        const PreviewTriangleIndexStream triangle_stream = preview_triangle_index_stream_from_faces(faces);
        if (triangle_stream.flat_indices.empty()) {
            continue;
        }
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, vertices.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(item, faces.size());
        PreviewModelMeshReport report;
        report.parsed_submesh_index = parsed_submesh_index;
        report.source_submesh_index = source_submesh_index;
        report.positions_path = string_or(item.get("positions_output_path"), "");
        report.uvs_path = string_or(item.get("texture_coordinates_output_path"), "");
        report.normals_path = string_or(item.get("normals_output_path"), "");
        report.indices_path = string_or(item.get("indices_output_path"), "");
        report.source_vertex_indices_path = string_or(item.get("source_vertex_indices_output_path"), "");
        report.source_face_indices_path = string_or(item.get("source_face_indices_output_path"), "");
        report.positions.reserve(vertices.size());
        for (const Vec3& vertex : vertices) {
            report.positions.push_back({
                (vertex[0] - center[0]) * scale,
                (vertex[1] - center[1]) * scale,
                (vertex[2] - center[2]) * scale,
            });
        }
        report.uvs = mesh_uvs_from_item(item);
        if (report.uvs.size() > report.positions.size()) {
            report.uvs.resize(report.positions.size());
        }
        report.normals = mesh_normals_from_item(item);
        if (report.normals.size() > report.positions.size()) {
            report.normals.resize(report.positions.size());
        }
        report.indices = triangle_stream.flat_indices;
        report.source_vertex_indices.reserve(vertices.size());
        for (std::size_t index = 0; index < vertices.size(); ++index) {
            const int source_vertex_index = index < source_vertices.size()
                ? source_vertices[index]
                : static_cast<int>(index);
            report.source_vertex_indices.push_back(source_vertex_index);
        }
        report.source_face_indices.reserve(triangle_stream.face_ordinals.size());
        for (const int face_ordinal : triangle_stream.face_ordinals) {
            const int source_face_index = face_ordinal >= 0 && static_cast<std::size_t>(face_ordinal) < source_faces.size()
                ? source_faces[static_cast<std::size_t>(face_ordinal)]
                : face_ordinal;
            report.source_face_indices.push_back(source_face_index);
        }
        vertex_count += static_cast<int>(report.positions.size());
        face_count += static_cast<int>(report.indices.size() / 3u);
        reports.push_back(std::move(report));
    }
    return preview_model_report_json(reports, vertex_count, face_count);
}

std::string run_preview_geometry(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    const std::string identity_output_path = string_or(root.get("identity_output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("preview geometry output_path is required");
    }
    const JsonValue* meshes = root.get("meshes");
    if (meshes == nullptr || meshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing meshes array");
    }
    std::vector<char> geometry;
    std::vector<char> identity;
    std::vector<PreviewGeometryBatchReport> batch_reports;
    int total_vertices = 0;
    for (const JsonValue& item : meshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int mesh_index = int_or(item.get("index"), -1);
        const std::vector<Vec3> positions = item_has_direct_geometry(item, "positions_binary", "positions")
            ? vertices_from_binary_or_json(item, "positions_binary", "positions")
            : mesh_vertices_from_item(item);
        if (mesh_index < 0 || positions.empty()) {
            continue;
        }
        PreviewTriangleIndexStream triangle_stream = preview_triangle_index_stream_from_binary_or_json(item, positions.size());
        std::vector<std::array<int, 3>> faces;
        if (triangle_stream.flat_indices.empty()) {
            faces = mesh_faces_from_item(item, positions.size());
            triangle_stream = preview_triangle_index_stream_from_faces(faces);
        }
        const std::vector<int>& flat_indices = triangle_stream.flat_indices;
        if (flat_indices.empty()) {
            continue;
        }
        const int source_submesh_index = int_or(item.get("source_submesh_index"), -1);
        const std::vector<int> source_vertices = mesh_source_vertex_indices_from_item(item, positions.size());
        const std::vector<int> source_faces = mesh_source_face_indices_from_item(
            item,
            faces.empty() ? triangle_stream.face_ordinals.size() : faces.size());
        std::vector<Vec3> normals = mesh_normals_from_item(item);
        int normal_repair_count = 0;
        if (normals.size() != positions.size()) {
            normals.assign(positions.size(), {0.0, 0.0, 1.0});
            normal_repair_count = static_cast<int>(positions.size());
        } else {
            for (Vec3& normal : normals) {
                bool repaired = false;
                normal = sanitize_normal_for_preview(normal, &repaired);
                if (repaired) {
                    ++normal_repair_count;
                }
            }
        }
        std::vector<Vec2> uvs = item_has_direct_geometry(item, "texture_coordinates_binary", "texture_coordinates")
            ? uvs_from_binary_or_json(item, "texture_coordinates_binary", "texture_coordinates")
            : mesh_uvs_from_item(item);
        const bool has_uvs = uvs.size() == positions.size();
        if (!has_uvs) {
            uvs.assign(positions.size(), {0.0, 0.0});
        }
        bool texture_wrap_repeat = false;
        if (has_uvs) {
            double min_u = uvs[0][0];
            double max_u = uvs[0][0];
            double min_v = uvs[0][1];
            double max_v = uvs[0][1];
            for (const Vec2& uv : uvs) {
                min_u = std::min(min_u, uv[0]);
                max_u = std::max(max_u, uv[0]);
                min_v = std::min(min_v, uv[1]);
                max_v = std::max(max_v, uv[1]);
            }
            texture_wrap_repeat = min_u < -0.05 || max_u > 1.05 || min_v < -0.05 || max_v > 1.05;
        }
        const Vec3 color = vec3_or(item.get("color"), {1.0, 1.0, 1.0});
        const PreviewSmoothNormalsResult smooth = build_preview_smoothed_normals(positions, normals, flat_indices);
        const PreviewTangentFrames tangents = build_preview_tangent_frames(positions, uvs, normals, flat_indices);
        PreviewGeometryBatchReport report;
        report.mesh_index = mesh_index;
        report.first_vertex = total_vertices;
        report.vertex_count = static_cast<int>(flat_indices.size());
        report.base_color = color;
        report.has_texture_coordinates = has_uvs;
        report.texture_wrap_repeat = texture_wrap_repeat;
        const double vertex_total = static_cast<double>(std::max<std::size_t>(1, positions.size()));
        report.normal_repair_count = normal_repair_count;
        report.normal_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(normal_repair_count) / vertex_total));
        report.tangent_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(count_false_values(tangents.tangent_valid)) / vertex_total));
        report.bitangent_finite_ratio = std::max(0.0, 1.0 - (static_cast<double>(count_false_values(tangents.bitangent_valid)) / vertex_total));
        report.uv_finite_ratio = has_uvs ? 1.0 : 0.0;
        report.smooth_normal_ratio = smooth.changed_ratio;
        report.position_y_min = positions[0][1];
        report.position_y_max = positions[0][1];
        for (const Vec3& position : positions) {
            report.position_y_min = std::min(report.position_y_min, position[1]);
            report.position_y_max = std::max(report.position_y_max, position[1]);
        }
        report.bounds_min = positions[static_cast<std::size_t>(flat_indices[0])];
        report.bounds_max = report.bounds_min;
        for (int vertex_index : flat_indices) {
            const Vec3& position = positions[static_cast<std::size_t>(vertex_index)];
            report.bounds_min[0] = std::min(report.bounds_min[0], position[0]);
            report.bounds_min[1] = std::min(report.bounds_min[1], position[1]);
            report.bounds_min[2] = std::min(report.bounds_min[2], position[2]);
            report.bounds_max[0] = std::max(report.bounds_max[0], position[0]);
            report.bounds_max[1] = std::max(report.bounds_max[1], position[1]);
            report.bounds_max[2] = std::max(report.bounds_max[2], position[2]);
        }
        int tangent_checked = 0;
        int tangent_valid = 0;
        const int identity_offset = static_cast<int>(identity.size());
        report.source_vertex_indices.reserve(flat_indices.size());
        report.source_face_indices.reserve(flat_indices.size() / 3);
        for (std::size_t emitted = 0; emitted < flat_indices.size(); ++emitted) {
            const int vertex_index = flat_indices[emitted];
            const std::size_t source = static_cast<std::size_t>(vertex_index);
            const std::size_t face_output_index = emitted / 3;
            const int face_ordinal = face_output_index < triangle_stream.face_ordinals.size()
                ? triangle_stream.face_ordinals[face_output_index]
                : static_cast<int>(face_output_index);
            const int source_vertex_index = source < source_vertices.size()
                ? source_vertices[source]
                : vertex_index;
            const int source_face_index = face_ordinal >= 0 && static_cast<std::size_t>(face_ordinal) < source_faces.size()
                ? source_faces[static_cast<std::size_t>(face_ordinal)]
                : face_ordinal;
            report.source_vertex_indices.push_back(source_vertex_index);
            if (emitted % 3 == 0) {
                report.source_face_indices.push_back(source_face_index);
            }
            if (!identity_output_path.empty()) {
                append_i32_le(identity, source_submesh_index);
                append_i32_le(identity, source_vertex_index);
                append_i32_le(identity, source_face_index);
            }
            const Vec3 barycentric = (emitted % 3 == 0)
                ? Vec3{1.0, 0.0, 0.0}
                : ((emitted % 3 == 1) ? Vec3{0.0, 1.0, 0.0} : Vec3{0.0, 0.0, 1.0});
            append_preview_vertex(
                geometry,
                positions[source],
                normals[source],
                color,
                uvs[source],
                tangents.tangents[source],
                tangents.bitangents[source],
                smooth.normals[source],
                barycentric);
            ++tangent_checked;
            if (preview_vertex_tangent_usable(normals[source], uvs[source], tangents.tangents[source], tangents.bitangents[source])) {
                ++tangent_valid;
            }
        }
        report.tangents_usable = tangent_checked > 0 && (static_cast<double>(tangent_valid) / static_cast<double>(tangent_checked)) >= 0.80;
        report.identity_offset = identity_offset;
        report.identity_size = static_cast<int>(identity.size()) - identity_offset;
        total_vertices += report.vertex_count;
        batch_reports.push_back(report);
    }
    write_binary_file(output_path, geometry, bool_or(root.get("append"), false));
    if (!identity_output_path.empty()) {
        write_binary_file(identity_output_path, identity, bool_or(root.get("append"), false));
    }
    return preview_geometry_report_json(batch_reports, total_vertices, static_cast<int>(geometry.size()), output_path);
}

std::string preview_identity_report_json(
    int source_submesh_index,
    int source_vertex_count,
    int source_face_count,
    int identity_size,
    const std::string& role,
    const std::string& part_name,
    bool editable
) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"preview_identity\""
        << ",\"source_submesh_index\":" << source_submesh_index
        << ",\"source_vertex_count\":" << source_vertex_count
        << ",\"source_face_count\":" << source_face_count
        << ",\"identity_stride_bytes\":12"
        << ",\"identity_size\":" << identity_size
        << ",\"role\":";
    write_escaped(out, role);
    out << ",\"part_name\":";
    write_escaped(out, part_name);
    out << ",\"editable\":" << (editable ? "true" : "false")
        << "}";
    return out.str();
}

std::string run_preview_identity(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("preview identity output_path is required");
    }
    const int source_submesh_index = int_or(root.get("source_submesh_index"), -1);
    const int vertex_count = std::max(0, int_or(root.get("vertex_count"), 0));
    const int source_vertex_start = int_or(root.get("source_vertex_start"), -1);
    const int source_vertex_range_count = std::max(0, int_or(root.get("source_vertex_count"), 0));
    const bool source_vertex_range = source_vertex_start >= 0 && source_vertex_range_count > 0;
    const int source_face_start = int_or(root.get("source_face_start"), -1);
    const int source_face_range_count = std::max(0, int_or(root.get("source_face_count"), 0));
    const bool source_face_range = source_face_start >= 0 && source_face_range_count > 0;
    const std::vector<int> source_vertices = source_vertex_range
        ? std::vector<int>()
        : int_vector_from_binary_or_json(root, "source_vertex_indices_binary", "source_vertex_indices");
    const std::vector<int> source_faces = source_face_range
        ? std::vector<int>()
        : int_vector_from_binary_or_json(root, "source_face_indices_binary", "source_face_indices");
    const std::string role = string_or(root.get("role"), "");
    const std::string part_name = string_or(root.get("part_name"), "");
    const std::string role_key = lower_ascii(role);
    const bool reference_role = role_key.find("reference") != std::string::npos || role_key.find("original") != std::string::npos;
    const bool editable = bool_or(root.get("editable"), source_submesh_index >= 0) && !reference_role;
    std::vector<char> identity;
    identity.reserve(static_cast<std::size_t>(vertex_count) * 12u);
    int max_source_vertex = -1;
    int max_source_face = -1;
    for (int value : source_vertices) {
        max_source_vertex = std::max(max_source_vertex, value);
    }
    if (source_vertex_range) {
        max_source_vertex = std::max(max_source_vertex, source_vertex_start + source_vertex_range_count - 1);
    }
    for (int value : source_faces) {
        max_source_face = std::max(max_source_face, value);
    }
    if (source_face_range) {
        max_source_face = std::max(max_source_face, source_face_start + source_face_range_count - 1);
    }
    for (int vertex_offset = 0; vertex_offset < vertex_count; ++vertex_offset) {
        const int source_vertex_index = source_vertex_range && vertex_offset < source_vertex_range_count
            ? source_vertex_start + vertex_offset
            : vertex_offset < static_cast<int>(source_vertices.size())
            ? source_vertices[static_cast<std::size_t>(vertex_offset)]
            : vertex_offset;
        const int face_offset = vertex_offset / 3;
        const int source_face_index = source_face_range && face_offset < source_face_range_count
            ? source_face_start + face_offset
            : face_offset < static_cast<int>(source_faces.size())
            ? source_faces[static_cast<std::size_t>(face_offset)]
            : face_offset;
        append_i32_le(identity, source_submesh_index);
        append_i32_le(identity, source_vertex_index);
        append_i32_le(identity, source_face_index);
    }
    write_binary_file(output_path, identity, bool_or(root.get("append"), true));
    return preview_identity_report_json(
        source_submesh_index,
        max_source_vertex >= 0 ? max_source_vertex + 1 : 0,
        max_source_face >= 0 ? max_source_face + 1 : 0,
        static_cast<int>(identity.size()),
        role,
        part_name,
        editable);
}

MeshSessionSubmesh mesh_session_submesh_from_item(const JsonValue& item) {
    if (const MeshSessionSubmesh* session = mesh_session_submesh_for_item(item)) {
        MeshSessionSubmesh stored_submesh = *session;
        if (item.get("name") != nullptr || item.get("part_name") != nullptr) {
            stored_submesh.name = string_or(item.get("name"), string_or(item.get("part_name"), stored_submesh.name));
        }
        if (item.get("material") != nullptr) {
            stored_submesh.material = string_or(item.get("material"), stored_submesh.material);
        }
        if (item.get("texture") != nullptr) {
            stored_submesh.texture = string_or(item.get("texture"), stored_submesh.texture);
        }
        if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
            if (extra_attrs->type == JsonValue::Type::Object) {
                stored_submesh.extra_attrs = *extra_attrs;
            }
        }
        return stored_submesh;
    }
    MeshSessionSubmesh stored_submesh;
    stored_submesh.name = string_or(item.get("name"), string_or(item.get("part_name"), ""));
    stored_submesh.material = string_or(item.get("material"), "");
    stored_submesh.texture = string_or(item.get("texture"), "");
    if (const JsonValue* extra_attrs = item.get("extra_attrs")) {
        if (extra_attrs->type == JsonValue::Type::Object) {
            stored_submesh.extra_attrs = *extra_attrs;
        }
    }
    stored_submesh.vertices = vertices_from_binary_or_json(item, "vertices_binary", "vertices");
    if (stored_submesh.vertices.empty()) {
        return stored_submesh;
    }
    stored_submesh.faces = faces_from_binary_or_json(item, stored_submesh.vertices.size());
    stored_submesh.source_face_indices = int_vector_from_binary_or_json(
        item,
        "source_face_indices_binary",
        "source_face_indices",
        "source_face_start",
        "source_face_count"
    );
    if (stored_submesh.source_face_indices.empty() && item.get("faces") != nullptr) {
        stored_submesh.source_face_indices = source_face_indices_from_faces_json(item.get("faces"), stored_submesh.vertices.size());
    }
    bool valid_source_faces = stored_submesh.source_face_indices.size() == stored_submesh.faces.size();
    for (const int source_face_index : stored_submesh.source_face_indices) {
        if (source_face_index < 0) {
            valid_source_faces = false;
            break;
        }
    }
    if (!valid_source_faces) {
        stored_submesh.source_face_indices = identity_indices(stored_submesh.faces.size());
    }
    stored_submesh.normals = vertices_from_binary_or_json(item, "normals_binary", "normals");
    if (stored_submesh.normals.size() != stored_submesh.vertices.size()) {
        stored_submesh.normals.clear();
    }
    stored_submesh.uvs = uvs_from_binary_or_json(item, "uvs_binary", "uvs");
    if (stored_submesh.uvs.size() != stored_submesh.vertices.size()) {
        stored_submesh.uvs.clear();
    }
    stored_submesh.tangents = vertices_from_binary_or_json(item, "tangents_binary", "tangents");
    if (stored_submesh.tangents.size() != stored_submesh.vertices.size()) {
        stored_submesh.tangents.clear();
    }
    stored_submesh.tangent_signs = double_vector_from_binary_or_json(item, "tangent_signs_binary", "tangent_signs");
    if (stored_submesh.tangent_signs.size() != stored_submesh.vertices.size()) {
        stored_submesh.tangent_signs.clear();
    }
    const BoneAssignments stored_bones = bone_assignments_from_binary(item);
    if (valid_bone_assignments(stored_bones) && stored_bones.indices.size() == stored_submesh.vertices.size()) {
        stored_submesh.bone_indices = stored_bones.indices;
        stored_submesh.bone_weights = stored_bones.weights;
    }
    stored_submesh.source_vertex_map = int_vector_from_binary_or_json(
        item,
        "source_vertex_map_binary",
        "source_vertex_map",
        "source_vertex_map_start",
        "source_vertex_map_count"
    );
    if (stored_submesh.source_vertex_map.size() != stored_submesh.vertices.size()) {
        stored_submesh.source_vertex_map.clear();
    }
    stored_submesh.source_vertex_offsets = source_vertex_offsets_from_item(item);
    if (stored_submesh.source_vertex_offsets.size() != stored_submesh.vertices.size()) {
        stored_submesh.source_vertex_offsets.clear();
    }
    return stored_submesh;
}

std::string run_mesh_session(const JsonValue& root) {
    const std::string session_id = string_or(root.get("session_id"), "");
    if (session_id.empty()) {
        throw std::runtime_error("missing mesh session_id");
    }
    std::string operation = string_or(root.get("operation"), "store");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (operation == "clear") {
        g_mesh_sessions.erase(session_id);
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_session\",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"submesh_count\":0,\"vertex_count\":0,\"face_count\":0}";
        return out.str();
    }

    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing mesh session submeshes");
    }
    std::map<int, MeshSessionSubmesh>& session = g_mesh_sessions[session_id];
    int stored = 0;
    int vertex_count = 0;
    int face_count = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        if (index < 0) {
            continue;
        }
        MeshSessionSubmesh stored_submesh = mesh_session_submesh_from_item(item);
        if (stored_submesh.vertices.empty()) {
            continue;
        }
        vertex_count += static_cast<int>(stored_submesh.vertices.size());
        face_count += static_cast<int>(stored_submesh.faces.size());
        session[index] = std::move(stored_submesh);
        ++stored;
    }

    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"mesh_session\",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"submesh_count\":" << stored
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count << "}";
    return out.str();
}

std::string mesh_editor_native_session_id(const std::string& session_id) {
    return "mesh-editor-session:" + session_id;
}

JsonValue mesh_editor_json_number(double value) {
    JsonValue result;
    result.type = JsonValue::Type::Number;
    result.number_value = value;
    return result;
}

JsonValue mesh_editor_json_string(const std::string& value) {
    JsonValue result;
    result.type = JsonValue::Type::String;
    result.string_value = value;
    return result;
}

JsonValue mesh_editor_json_bool(bool value) {
    JsonValue result;
    result.type = JsonValue::Type::Bool;
    result.bool_value = value;
    return result;
}

std::string mesh_editor_safe_path_token(const std::string& value) {
    std::string result;
    result.reserve(value.size());
    for (const char ch : value) {
        const unsigned char raw = static_cast<unsigned char>(ch);
        if ((raw >= 'a' && raw <= 'z')
            || (raw >= 'A' && raw <= 'Z')
            || (raw >= '0' && raw <= '9')
            || ch == '-' || ch == '_') {
            result.push_back(ch);
        } else {
            result.push_back('_');
        }
    }
    return result.empty() ? "session" : result;
}

std::string mesh_editor_join_path(const std::string& directory, const std::string& filename) {
    if (directory.empty()) {
        return std::string();
    }
    const char last = directory[directory.size() - 1];
    if (last == '/' || last == '\\') {
        return directory + filename;
    }
    return directory + "/" + filename;
}

std::string mesh_editor_delta_path(
    const std::string& directory,
    const std::string& session_id,
    int submesh_index,
    const std::string& role,
    const std::string& suffix
) {
    std::ostringstream name;
    name << "mesh_editor_" << mesh_editor_safe_path_token(session_id)
         << "_" << submesh_index << "_" << role << suffix;
    return mesh_editor_join_path(directory, name.str());
}

void mesh_editor_add_delta_output_paths(
    JsonValue& item,
    const std::string& directory,
    const std::string& session_id,
    int submesh_index
) {
    if (directory.empty()) {
        return;
    }
    item.object_value["changed_vertices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "changed_vertices", ".bin"));
    item.object_value["changed_positions_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "changed_positions", ".bin"));
    item.object_value["before_positions_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "before_positions", ".bin"));
    item.object_value["preview_vertex_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "preview_vertices", ".bin"));
    item.object_value["vertices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertices", ".bin"));
    item.object_value["faces_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "faces", ".bin"));
    item.object_value["normals_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "normals", ".bin"));
    item.object_value["uvs_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "uvs", ".bin"));
    item.object_value["tangents_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "tangents", ".bin"));
    item.object_value["tangent_signs_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "tangent_signs", ".bin"));
    item.object_value["bone_counts_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_counts", ".bin"));
    item.object_value["bone_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_indices", ".bin"));
    item.object_value["bone_weights_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "bone_weights", ".bin"));
    item.object_value["source_vertex_map_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "source_vertex_map", ".bin"));
    item.object_value["source_vertex_offsets_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "source_vertex_offsets", ".bin"));
    item.object_value["copy_vertex_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "copy_vertex_indices", ".bin"));
    item.object_value["vertex_blend_indices_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertex_blend_indices", ".bin"));
    item.object_value["vertex_blend_factors_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "vertex_blend_factors", ".bin"));
    item.object_value["index_map_output_path"] = mesh_editor_json_string(mesh_editor_delta_path(directory, session_id, submesh_index, "index_map", ".bin"));
}

void mesh_editor_set_result_output_paths(
    SubmeshMeshEditResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.changed_positions_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_positions", ".bin");
    result.vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertices", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.tangents_path = mesh_editor_delta_path(directory, session_id, result.index, "tangents", ".bin");
    result.tangent_signs_path = mesh_editor_delta_path(directory, session_id, result.index, "tangent_signs", ".bin");
    result.bone_counts_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_counts", ".bin");
    result.bone_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_indices", ".bin");
    result.bone_weights_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_weights", ".bin");
    result.source_vertex_map_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_map", ".bin");
    result.source_vertex_offsets_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_offsets", ".bin");
    result.copy_vertex_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "copy_vertex_indices", ".bin");
    result.vertex_blend_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertex_blend_indices", ".bin");
    result.vertex_blend_factors_path = mesh_editor_delta_path(directory, session_id, result.index, "vertex_blend_factors", ".bin");
    result.index_map_path = mesh_editor_delta_path(directory, session_id, result.index, "index_map", ".bin");
}

bool mesh_editor_is_normal_operation(const std::string& operation) {
    return operation == "recalculate_normals"
        || operation == "weighted_normals"
        || operation == "flip_normals"
        || operation == "sharpen_normals"
        || operation == "soften_normals"
        || operation == "copy_normals";
}

bool mesh_editor_is_tangent_operation(const std::string& operation) {
    return operation == "generate_tangents";
}

bool mesh_editor_is_uv_operation(const std::string& operation) {
    return operation == "uv_transform";
}

void mesh_editor_set_normal_result_output_paths(
    SubmeshNormalsResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.preview_vertex_path = mesh_editor_delta_path(directory, session_id, result.index, "normal_preview_vertices", ".bin");
    result.preview_triangle_path = mesh_editor_delta_path(directory, session_id, result.index, "normal_preview_triangles", ".bin");
}

bool mesh_editor_normals_result_changed(const SubmeshNormalsResult& result) {
    return !result.changed_vertices.empty() || !result.faces.empty();
}

SubmeshMeshEditResult mesh_editor_result_from_normals_result(const SubmeshNormalsResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "normals";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions.reserve(source.changed_vertices.size());
    for (const int vertex_index : source.changed_vertices) {
        if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < source.vertices.size()) {
            result.changed_positions.push_back(source.vertices[static_cast<std::size_t>(vertex_index)]);
        }
    }
    result.changed_positions_path = source.preview_vertex_path;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.source_vertex_map = source.source_vertex_map;
    if (!source.faces.empty()) {
        result.vertices = source.vertices;
        result.preview_triangle_path = source.preview_triangle_path;
    }
    result.sparse = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_normals_results(
    const std::vector<SubmeshNormalsResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshNormalsResult& source : sources) {
        if (mesh_editor_normals_result_changed(source)) {
            results.push_back(mesh_editor_result_from_normals_result(source));
        }
    }
    return results;
}

SubmeshNormalsResult mesh_editor_normal_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& operation,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshNormalsResult result;
    result.index = submesh_index;
    result.vertices = restored.vertices;
    result.normals = restored.normals;
    result.uvs = restored.uvs;
    result.source_vertex_map = restored.source_vertex_map;
    if (operation == "flip_normals" && current.faces != restored.faces) {
        result.faces = restored.faces;
    }
    mesh_editor_set_normal_result_output_paths(result, delta_output_dir, session_id);

    if (current.normals.size() == restored.normals.size()) {
        for (std::size_t normal_index = 0; normal_index < restored.normals.size(); ++normal_index) {
            if (!same_vec3(current.normals[normal_index], restored.normals[normal_index])) {
                result.changed_vertices.push_back(static_cast<int>(normal_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.normals.size());
        for (std::size_t normal_index = 0; normal_index < restored.normals.size(); ++normal_index) {
            result.changed_vertices.push_back(static_cast<int>(normal_index));
        }
    }
    return result;
}

void mesh_editor_set_uv_result_output_paths(
    SubmeshUvTransformResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.preview_vertex_path = mesh_editor_delta_path(directory, session_id, result.index, "uv_preview_vertices", ".bin");
}

bool mesh_editor_uv_result_changed(const SubmeshUvTransformResult& result) {
    return result.clear_uvs || !result.changed_vertices.empty() || result.status != "ok";
}

SubmeshMeshEditResult mesh_editor_result_from_uv_result(const SubmeshUvTransformResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "uv_transform";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions_path = source.preview_vertex_path;
    if (source.vertices.size() == source.uvs.size()) {
        result.changed_positions.reserve(source.changed_vertices.size());
        for (const int vertex_index : source.changed_vertices) {
            if (vertex_index >= 0 && static_cast<std::size_t>(vertex_index) < source.vertices.size()) {
                result.changed_positions.push_back(source.vertices[static_cast<std::size_t>(vertex_index)]);
            }
        }
    }
    result.preview_normals = source.normals;
    result.preview_uvs = source.uvs;
    result.sparse = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_uv_results(
    const std::vector<SubmeshUvTransformResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshUvTransformResult& source : sources) {
        if (mesh_editor_uv_result_changed(source)) {
            results.push_back(mesh_editor_result_from_uv_result(source));
        }
    }
    return results;
}

bool mesh_editor_auto_uv_result_changed(const SubmeshAutoUvResult& result) {
    return result.status == "ok" && (result.topology_changed || !result.changed_vertices.empty());
}

SubmeshMeshEditResult mesh_editor_result_from_auto_uv_result(
    const SubmeshAutoUvResult& source,
    const MeshSessionSubmesh* current
) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "auto_uv";
    result.topology_changed = source.topology_changed;
    result.vertices = source.vertices;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.tangents = source.tangents;
    result.tangent_signs = source.tangent_signs;
    result.bones = source.bones;
    result.source_vertex_map = source.source_vertex_map;
    result.source_vertex_offsets = source.source_vertex_offsets;
    result.changed_vertices = source.changed_vertices;
    result.vertices_path = source.vertices_path;
    result.faces_path = source.faces_path;
    result.uvs_path = source.uvs_path;
    result.normals_path = source.normals_path;
    result.tangents_path = source.tangents_path;
    result.tangent_signs_path = source.tangent_signs_path;
    result.bone_counts_path = source.bone_counts_path;
    result.bone_indices_path = source.bone_indices_path;
    result.bone_weights_path = source.bone_weights_path;
    result.source_vertex_map_path = source.source_vertex_map_path;
    result.source_vertex_offsets_path = source.source_vertex_offsets_path;
    result.changed_vertices_path = source.changed_vertices_path;
    if (current != nullptr && current->source_face_indices.size() == result.faces.size()) {
        result.source_face_indices = current->source_face_indices;
    } else {
        result.source_face_indices = identity_indices(result.faces.size());
    }
    result.added_vertices = std::max(0, source.output_vertex_count - source.input_vertex_count);
    result.removed_vertices = std::max(0, source.input_vertex_count - source.output_vertex_count);
    result.added_faces = std::max(0, source.output_face_count - source.input_face_count);
    result.removed_faces = std::max(0, source.input_face_count - source.output_face_count);
    return result;
}

MeshSessionSubmesh mesh_editor_submesh_after_auto_uv(
    const MeshSessionSubmesh& current,
    const SubmeshAutoUvResult& source
) {
    MeshSessionSubmesh updated = current;
    if (source.topology_changed) {
        updated.vertices = source.vertices;
        updated.faces = source.faces;
        updated.source_face_indices = current.source_face_indices.size() == source.faces.size()
            ? current.source_face_indices
            : identity_indices(source.faces.size());
        updated.normals = source.normals.size() == source.vertices.size()
            ? source.normals
            : compute_smooth_normals(source.vertices, source.faces);
        updated.tangents = source.tangents.size() == source.vertices.size() ? source.tangents : std::vector<Vec3>();
        updated.tangent_signs = source.tangent_signs.size() == source.vertices.size() ? source.tangent_signs : std::vector<double>();
        if (valid_bone_assignments(source.bones) && source.bones.indices.size() == source.vertices.size()) {
            updated.bone_indices = source.bones.indices;
            updated.bone_weights = source.bones.weights;
        } else {
            updated.bone_indices.clear();
            updated.bone_weights.clear();
        }
        updated.source_vertex_map = source.source_vertex_map.size() == source.vertices.size()
            ? source.source_vertex_map
            : std::vector<int>();
        updated.source_vertex_offsets = source.source_vertex_offsets.size() == source.vertices.size()
            ? source.source_vertex_offsets
            : std::vector<int>();
    }
    if (source.uvs.size() == updated.vertices.size()) {
        updated.uvs = source.uvs;
    }
    return updated;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_auto_uv_results(
    const std::vector<SubmeshAutoUvResult>& sources,
    std::map<int, MeshSessionSubmesh>& native_session
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshAutoUvResult& source : sources) {
        if (!mesh_editor_auto_uv_result_changed(source)) {
            continue;
        }
        const auto current_found = native_session.find(source.index);
        const MeshSessionSubmesh* current = current_found != native_session.end() ? &current_found->second : nullptr;
        results.push_back(mesh_editor_result_from_auto_uv_result(source, current));
        if (source.status == "ok" && current != nullptr && source.uvs.size() == source.vertices.size()) {
            native_session[source.index] = mesh_editor_submesh_after_auto_uv(*current, source);
        }
    }
    return results;
}

SubmeshUvTransformResult mesh_editor_uv_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshUvTransformResult result;
    result.index = submesh_index;
    mesh_editor_set_uv_result_output_paths(result, delta_output_dir, session_id);
    if (restored.uvs.size() != restored.vertices.size()) {
        result.clear_uvs = true;
        const std::size_t vertex_count = std::max(current.vertices.size(), current.uvs.size());
        result.changed_vertices.reserve(vertex_count);
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
        }
        return result;
    }
    result.uvs = restored.uvs;
    if (current.uvs.size() == restored.uvs.size()) {
        for (std::size_t uv_index = 0; uv_index < restored.uvs.size(); ++uv_index) {
            if (!same_vec2(current.uvs[uv_index], restored.uvs[uv_index])) {
                result.changed_vertices.push_back(static_cast<int>(uv_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.uvs.size());
        for (std::size_t uv_index = 0; uv_index < restored.uvs.size(); ++uv_index) {
            result.changed_vertices.push_back(static_cast<int>(uv_index));
        }
    }
    return result;
}

void mesh_editor_set_tangent_result_output_paths(
    SubmeshTangentsResult& result,
    const std::string& directory,
    const std::string& session_id
) {
    if (directory.empty() || result.index < 0) {
        return;
    }
    result.vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "vertices", ".bin");
    result.faces_path = mesh_editor_delta_path(directory, session_id, result.index, "faces", ".bin");
    result.normals_path = mesh_editor_delta_path(directory, session_id, result.index, "normals", ".bin");
    result.uvs_path = mesh_editor_delta_path(directory, session_id, result.index, "uvs", ".bin");
    result.tangents_path = mesh_editor_delta_path(directory, session_id, result.index, "tangents", ".bin");
    result.tangent_signs_path = mesh_editor_delta_path(directory, session_id, result.index, "tangent_signs", ".bin");
    result.changed_vertices_path = mesh_editor_delta_path(directory, session_id, result.index, "changed_vertices", ".bin");
    result.bone_counts_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_counts", ".bin");
    result.bone_indices_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_indices", ".bin");
    result.bone_weights_path = mesh_editor_delta_path(directory, session_id, result.index, "bone_weights", ".bin");
    result.source_vertex_map_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_map", ".bin");
    result.source_vertex_offsets_path = mesh_editor_delta_path(directory, session_id, result.index, "source_vertex_offsets", ".bin");
}

bool mesh_editor_tangents_result_changed(const SubmeshTangentsResult& result) {
    return result.clear_tangents || result.topology_split_applied || !result.changed_vertices.empty();
}

SubmeshMeshEditResult mesh_editor_result_from_tangents_result(const SubmeshTangentsResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "generate_tangents";
    result.topology_changed = source.topology_split_applied;
    result.changed_vertices = source.changed_vertices;
    if (source.topology_split_applied) {
        result.vertices = source.vertices;
        result.faces = source.faces;
        result.normals = source.normals;
        result.preview_uvs = source.uvs;
        result.tangents = source.tangents;
        result.tangent_signs = source.tangent_signs;
        result.bones = source.bones;
        result.source_vertex_map = source.source_vertex_map;
        result.source_vertex_offsets = source.source_vertex_offsets;
    }
    result.sparse = !source.topology_split_applied;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_tangents_results(
    const std::vector<SubmeshTangentsResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshTangentsResult& source : sources) {
        if (mesh_editor_tangents_result_changed(source)) {
            results.push_back(mesh_editor_result_from_tangents_result(source));
        }
    }
    return results;
}

SubmeshTangentsResult mesh_editor_tangent_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshTangentsResult result;
    result.index = submesh_index;
    result.tangent_backend = "history";
    mesh_editor_set_tangent_result_output_paths(result, delta_output_dir, session_id);
    if (restored.tangents.size() != restored.vertices.size()) {
        result.clear_tangents = true;
        const std::size_t vertex_count = std::max(current.vertices.size(), current.tangents.size());
        result.changed_vertices.reserve(vertex_count);
        for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
        }
        return result;
    }
    result.tangents = restored.tangents;
    if (current.tangents.size() == restored.tangents.size()) {
        for (std::size_t tangent_index = 0; tangent_index < restored.tangents.size(); ++tangent_index) {
            if (!same_vec3(current.tangents[tangent_index], restored.tangents[tangent_index])) {
                result.changed_vertices.push_back(static_cast<int>(tangent_index));
            }
        }
    } else {
        result.changed_vertices.reserve(restored.tangents.size());
        for (std::size_t tangent_index = 0; tangent_index < restored.tangents.size(); ++tangent_index) {
            result.changed_vertices.push_back(static_cast<int>(tangent_index));
        }
    }
    return result;
}

SubmeshMeshEditResult mesh_editor_history_report_result(
    int submesh_index,
    const MeshSessionSubmesh& current,
    const MeshSessionSubmesh& restored,
    const std::string& action,
    bool history_topology_changed,
    const std::string& delta_output_dir,
    const std::string& session_id
) {
    SubmeshMeshEditResult result;
    result.index = submesh_index;
    result.action = action;
    result.topology_changed = history_topology_changed
        || current.vertices.size() != restored.vertices.size()
        || current.faces != restored.faces;
    const bool material_metadata_changed = !mesh_editor_same_material_metadata(current, restored);
    if (result.topology_changed || material_metadata_changed) {
        result.name = restored.name;
        result.material = restored.material;
        result.texture = restored.texture;
        result.extra_attrs = restored.extra_attrs;
        result.material_metadata_changed = true;
    }
    result.added_vertices = static_cast<int>(restored.vertices.size() > current.vertices.size() ? restored.vertices.size() - current.vertices.size() : 0);
    result.removed_vertices = static_cast<int>(current.vertices.size() > restored.vertices.size() ? current.vertices.size() - restored.vertices.size() : 0);
    result.added_faces = static_cast<int>(restored.faces.size() > current.faces.size() ? restored.faces.size() - current.faces.size() : 0);
    result.removed_faces = static_cast<int>(current.faces.size() > restored.faces.size() ? current.faces.size() - restored.faces.size() : 0);
    mesh_editor_set_result_output_paths(result, delta_output_dir, session_id);

    if (result.topology_changed || material_metadata_changed) {
        result.vertices = restored.vertices;
        result.faces = restored.faces;
        result.normals = restored.normals;
        result.preview_uvs = restored.uvs;
        result.tangents = restored.tangents;
        result.tangent_signs = restored.tangent_signs;
        result.bones.indices = restored.bone_indices;
        result.bones.weights = restored.bone_weights;
        result.source_vertex_map = restored.source_vertex_map;
        result.source_vertex_offsets = restored.source_vertex_offsets;
        result.suppress_vertex_remap_report = true;
    }
    if (result.topology_changed) {
        return result;
    }

    result.sparse = true;
    const std::size_t vertex_count = std::min(current.vertices.size(), restored.vertices.size());
    for (std::size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
        if (current.vertices[vertex_index] != restored.vertices[vertex_index]) {
            result.changed_vertices.push_back(static_cast<int>(vertex_index));
            result.changed_positions.push_back(restored.vertices[vertex_index]);
        }
    }
    return result;
}

bool mesh_editor_key_to_index(const std::string& text, int& output) {
    if (text.empty()) {
        return false;
    }
    char* end = nullptr;
    errno = 0;
    const long parsed = std::strtol(text.c_str(), &end, 10);
    if (errno != 0 || end == text.c_str() || *end != '\0' || parsed < 0 || parsed > INT_MAX) {
        return false;
    }
    output = static_cast<int>(parsed);
    return true;
}

std::set<int> mesh_editor_indices_from_json(const JsonValue* value) {
    std::set<int> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const std::string& binary_key : {"indices_binary", "selected_vertices_binary", "selected_faces_binary"}) {
            if (value->get(binary_key) != nullptr) {
                const std::vector<int> values = int_vector_from_binary_or_json(*value, binary_key, "indices", "start", "count");
                for (const int index : values) {
                    if (index >= 0) {
                        result.insert(index);
                    }
                }
            }
        }
        if (!result.empty()) {
            return result;
        }
        const int start = int_or(value->get("start"), int_or(value->get("selected_start"), -1));
        const int count = int_or(value->get("count"), int_or(value->get("selected_count"), 0));
        if (start >= 0 && count > 0) {
            for (int offset = 0; offset < count; ++offset) {
                result.insert(start + offset);
            }
        }
        const JsonValue* indices = value->get("indices");
        if (indices != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(indices);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        const JsonValue* vertices = value->get("vertices");
        if (vertices != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(vertices);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        const JsonValue* faces = value->get("faces");
        if (faces != nullptr) {
            const std::set<int> explicit_indices = mesh_editor_indices_from_json(faces);
            result.insert(explicit_indices.begin(), explicit_indices.end());
        }
        return result;
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        int index = -1;
        if (strict_int_or(&item, index) && index >= 0) {
            result.insert(index);
        }
    }
    return result;
}

std::set<std::array<int, 2>> mesh_editor_edges_from_json(const JsonValue* value) {
    std::set<std::array<int, 2>> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        const JsonValue* binary = value->get("edges_binary");
        if (binary == nullptr) {
            binary = value->get("selected_edges_binary");
        }
        if (binary == nullptr) {
            binary = value->get("indices_binary");
        }
        if (binary != nullptr) {
            const std::vector<int> raw = int_vector_from_binary(binary);
            for (std::size_t offset = 0; offset + 1 < raw.size(); offset += 2) {
                const int left = raw[offset];
                const int right = raw[offset + 1];
                if (left >= 0 && right >= 0 && left != right) {
                    result.insert(edge_key(left, right));
                }
            }
            return result;
        }
        const JsonValue* edges = value->get("edges");
        if (edges == nullptr) {
            edges = value->get("indices");
        }
        if (edges == nullptr) {
            edges = value->get("selected_edges");
        }
        return mesh_editor_edges_from_json(edges);
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Array || item.array_value.size() < 2) {
            continue;
        }
        int left = -1;
        int right = -1;
        if (strict_int_or(&item.array_value[0], left) && strict_int_or(&item.array_value[1], right) && left >= 0 && right >= 0 && left != right) {
            result.insert(edge_key(left, right));
        }
    }
    return result;
}

const JsonValue* mesh_editor_group_values(const JsonValue& item, const std::string& preferred_key) {
    if (const JsonValue* value = item.get("indices")) {
        return value;
    }
    if (const JsonValue* value = item.get(preferred_key)) {
        return value;
    }
    if (const JsonValue* value = item.get("selected")) {
        return value;
    }
    return &item;
}

std::vector<int> mesh_editor_index_vector_from_json(const JsonValue* value) {
    std::vector<int> result;
    if (value == nullptr) {
        return result;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const std::string& binary_key : {"indices_binary", "selected_vertices_binary", "selected_faces_binary"}) {
            if (value->get(binary_key) != nullptr) {
                const std::vector<int> values = int_vector_from_binary_or_json(
                    *value,
                    binary_key,
                    "indices",
                    "start",
                    "count"
                );
                for (const int index : values) {
                    if (index >= 0) {
                        result.push_back(index);
                    }
                }
                if (!result.empty()) {
                    return result;
                }
            }
        }
        const int start = int_or(value->get("start"), int_or(value->get("selected_start"), -1));
        const int count = int_or(value->get("count"), int_or(value->get("selected_count"), 0));
        if (start >= 0 && count > 0) {
            result.reserve(static_cast<std::size_t>(count));
            for (int offset = 0; offset < count; ++offset) {
                result.push_back(start + offset);
            }
            return result;
        }
        for (const std::string& key : {"indices", "vertices", "faces"}) {
            if (const JsonValue* nested = value->get(key)) {
                result = mesh_editor_index_vector_from_json(nested);
                if (!result.empty()) {
                    return result;
                }
            }
        }
        return result;
    }
    if (value->type != JsonValue::Type::Array) {
        return result;
    }
    result.reserve(value->array_value.size());
    for (const JsonValue& item : value->array_value) {
        int index = -1;
        if (strict_int_or(&item, index) && index >= 0) {
            result.push_back(index);
        }
    }
    return result;
}

std::map<int, double> mesh_editor_vertex_weights_from_group(const JsonValue& item) {
    std::map<int, double> weights;
    const std::vector<int> indices = mesh_editor_index_vector_from_json(mesh_editor_group_values(item, "vertices"));
    const JsonValue* binary = item.get("weights_binary");
    if (binary == nullptr) {
        binary = item.get("vertex_weights_binary");
    }
    if (binary == nullptr) {
        binary = item.get("source_vertex_weights_binary");
    }
    if (binary != nullptr) {
        const std::vector<double> values = double_vector_from_f32_or_f64_binary(binary);
        if (values.size() == indices.size()) {
            for (std::size_t offset = 0; offset < indices.size(); ++offset) {
                const int index = indices[offset];
                const double weight = std::max(0.0, std::min(1.0, values[offset]));
                if (index >= 0 && weight > 0.0) {
                    weights[index] = std::max(weights[index], weight);
                }
            }
        }
        return weights;
    }
    const JsonValue* raw_weights = item.get("weights");
    if (raw_weights == nullptr) {
        raw_weights = item.get("vertex_weights");
    }
    if (raw_weights == nullptr) {
        raw_weights = item.get("source_vertex_weights");
    }
    if (raw_weights == nullptr || raw_weights->type != JsonValue::Type::Array) {
        return weights;
    }
    for (std::size_t offset = 0; offset < raw_weights->array_value.size(); ++offset) {
        const JsonValue& raw = raw_weights->array_value[offset];
        int index = -1;
        double weight = 0.0;
        if (raw.type == JsonValue::Type::Array && raw.array_value.size() >= 2) {
            index = int_or(&raw.array_value[0], -1);
            weight = number_or(&raw.array_value[1], 0.0);
        } else if (offset < indices.size()) {
            index = indices[offset];
            weight = number_or(&raw, 0.0);
        }
        weight = std::max(0.0, std::min(1.0, weight));
        if (index >= 0 && weight > 0.0) {
            weights[index] = std::max(weights[index], weight);
        }
    }
    return weights;
}

void mesh_editor_read_index_groups(
    const JsonValue* value,
    const std::string& preferred_key,
    std::map<int, std::set<int>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            const std::set<int> indices = mesh_editor_indices_from_json(mesh_editor_group_values(item, preferred_key));
            if (!indices.empty()) {
                target[index] = indices;
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index)) {
                continue;
            }
            const JsonValue* values = &entry.second;
            if (entry.second.type == JsonValue::Type::Object) {
                values = mesh_editor_group_values(entry.second, preferred_key);
            }
            const std::set<int> indices = mesh_editor_indices_from_json(values);
            if (!indices.empty()) {
                target[index] = indices;
            }
        }
    }
}

void mesh_editor_read_vertex_weight_groups(
    const JsonValue* value,
    std::map<int, std::map<int, double>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            std::map<int, double> weights = mesh_editor_vertex_weights_from_group(item);
            if (!weights.empty()) {
                target[index] = std::move(weights);
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index) || entry.second.type != JsonValue::Type::Object) {
                continue;
            }
            std::map<int, double> weights = mesh_editor_vertex_weights_from_group(entry.second);
            if (!weights.empty()) {
                target[index] = std::move(weights);
            }
        }
    }
}

void mesh_editor_read_edge_groups(
    const JsonValue* value,
    std::map<int, std::set<std::array<int, 2>>>& target
) {
    if (value == nullptr) {
        return;
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index < 0) {
                continue;
            }
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(mesh_editor_group_values(item, "edges"));
            if (!edges.empty()) {
                target[index] = edges;
            }
        }
        return;
    }
    if (value->type == JsonValue::Type::Object) {
        for (const auto& entry : value->object_value) {
            int index = -1;
            if (!mesh_editor_key_to_index(entry.first, index)) {
                continue;
            }
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(&entry.second);
            if (!edges.empty()) {
                target[index] = edges;
            }
        }
    }
}

void mesh_editor_prune_vertex_weights_to_selection(MeshEditorSelection& selection) {
    for (auto iter = selection.vertex_weights.begin(); iter != selection.vertex_weights.end();) {
        const auto selected = selection.vertices.find(iter->first);
        if (selected == selection.vertices.end()) {
            iter = selection.vertex_weights.erase(iter);
            continue;
        }
        for (auto weight_iter = iter->second.begin(); weight_iter != iter->second.end();) {
            if (selected->second.find(weight_iter->first) == selected->second.end()) {
                weight_iter = iter->second.erase(weight_iter);
            } else {
                ++weight_iter;
            }
        }
        if (iter->second.empty()) {
            iter = selection.vertex_weights.erase(iter);
        } else {
            ++iter;
        }
    }
}

void mesh_editor_add_screen_brush_selection(
    const MeshEditorSession* session,
    const JsonValue* raw_selection,
    MeshEditorSelection& selection
) {
    if (session == nullptr || raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return;
    }
    const JsonValue* raw_brush = raw_selection->get("screen_brush");
    if (raw_brush == nullptr || raw_brush->type != JsonValue::Type::Object) {
        return;
    }
    const std::string target_mode = lower_ascii(string_or(
        raw_selection->get("target_mode"),
        string_or(raw_selection->get("selection_target"), string_or(raw_brush->get("target_mode"), "vertex"))
    ));
    const std::string falloff = lower_ascii(string_or(raw_selection->get("falloff"), string_or(raw_brush->get("falloff"), "smooth")));
    const std::string depth_mode = lower_ascii(string_or(
        raw_selection->get("selection_depth_mode"),
        string_or(raw_selection->get("depth_mode"), string_or(raw_brush->get("selection_depth_mode"), string_or(raw_brush->get("depth_mode"), "xray")))
    ));
    const double raw_x = number_or(raw_brush->get("x"), number_or(raw_brush->get("cursor_x"), number_or(raw_brush->get("screen_x"), std::numeric_limits<double>::quiet_NaN())));
    const double raw_y = number_or(raw_brush->get("y"), number_or(raw_brush->get("cursor_y"), number_or(raw_brush->get("screen_y"), std::numeric_limits<double>::quiet_NaN())));
    const double radius_pixels = std::max(
        number_or(raw_brush->get("radius_pixels"), number_or(raw_brush->get("brush_radius_pixels"), number_or(raw_brush->get("pixels"), number_or(raw_brush->get("radius"), 0.0)))),
        0.0
    );
    const bool has_screen_point = std::isfinite(raw_x) && std::isfinite(raw_y) && radius_pixels >= 0.0;
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_brush);
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
    if (depth_mode != "xray") {
        depth_mask_storage = mesh_editor_screen_brush_depth_mask(session, *raw_brush);
        if (depth_mask_storage.valid) {
            depth_mask = &depth_mask_storage;
        }
    }
    if (target_mode == "source") {
        if (!has_screen_point) {
            return;
        }
        int best_source_index = mesh_editor_pick_source_with_screen_ray(session, *raw_brush, projection);
        if (best_source_index >= 0) {
            selection.source_indices.insert(best_source_index);
            return;
        }
        double best_distance = radius_pixels;
        for (const auto& entry : session->submeshes) {
            JsonValue item;
            item.type = JsonValue::Type::Object;
            item.object_value["index"] = mesh_editor_json_number(entry.first);
            if (!mesh_editor_screen_brush_submesh_allowed(item, *raw_brush)) {
                continue;
            }
            const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
            for (const Vec3& vertex : entry.second.vertices) {
                double screen_x = 0.0;
                double screen_y = 0.0;
                double depth_z = 0.0;
                if (!mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_brush,
                        entry_projection,
                        vertex,
                        screen_x,
                        screen_y,
                        depth_mask != nullptr ? &depth_z : nullptr)) {
                    continue;
                }
                const double distance = std::hypot(raw_x - screen_x, raw_y - screen_y);
                if (distance >= best_distance) {
                    continue;
                }
                if (!mesh_editor_screen_brush_depth_visible(depth_mask, screen_x, screen_y, depth_z)) {
                    continue;
                }
                best_distance = distance;
                best_source_index = entry.first;
            }
        }
        if (best_source_index >= 0) {
            selection.source_indices.insert(best_source_index);
        }
        return;
    }
    for (const auto& entry : session->submeshes) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        if (!mesh_editor_screen_brush_submesh_allowed(item, *raw_brush)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        MeshEditorScreenRay screen_ray;
        const bool has_screen_ray = (target_mode == "edge" || target_mode == "face")
            && mesh_editor_screen_ray_from_projection(*raw_brush, entry_projection, screen_ray);
        if (target_mode == "edge") {
            if (!has_screen_point) {
                continue;
            }
            std::set<std::array<int, 2>>& edges = selection.edges[entry.first];
            for (const std::array<int, 3>& face : entry.second.faces) {
                const std::array<std::array<int, 2>, 3> face_edges{{
                    {face[0], face[1]},
                    {face[1], face[2]},
                    {face[2], face[0]},
                }};
                for (std::array<int, 2> edge : face_edges) {
                    if (edge[0] < 0 || edge[1] < 0 || edge[0] == edge[1]) {
                        continue;
                    }
                    if (static_cast<std::size_t>(edge[0]) >= entry.second.vertices.size()
                        || static_cast<std::size_t>(edge[1]) >= entry.second.vertices.size()) {
                        continue;
                    }
                    const Vec3 edge_start = entry.second.vertices[static_cast<std::size_t>(edge[0])];
                    const Vec3 edge_end = entry.second.vertices[static_cast<std::size_t>(edge[1])];
                    if (has_screen_ray) {
                        double ray_distance = 0.0;
                        Vec3 edge_hit{};
                        const Vec3 edge_midpoint = scale_vec3(add_vec3(edge_start, edge_end), 0.5);
                        const double radius_world = std::max(
                            mesh_editor_screen_radius_units_at_center(raw_brush, edge_midpoint, entry.first),
                            1e-8
                        );
                        if (mesh_editor_ray_segment_distance(screen_ray, edge_start, edge_end, ray_distance, edge_hit)
                            && ray_distance <= radius_world) {
                            bool visible = true;
                            if (depth_mask != nullptr) {
                                double hit_x = 0.0;
                                double hit_y = 0.0;
                                double hit_depth = 0.0;
                                visible = project_vertex_with_matrix_depth(
                                    entry_projection.world_view_projection,
                                    edge_hit,
                                    entry_projection.viewport_x,
                                    entry_projection.viewport_y,
                                    entry_projection.viewport_width,
                                    entry_projection.viewport_height,
                                    hit_x,
                                    hit_y,
                                    hit_depth
                                ) && mesh_editor_screen_brush_depth_visible(depth_mask, hit_x, hit_y, hit_depth);
                            }
                            if (visible) {
                                if (edge[1] < edge[0]) {
                                    std::swap(edge[0], edge[1]);
                                }
                                edges.insert(edge);
                                continue;
                            }
                        }
                    }
                    double ax = 0.0;
                    double ay = 0.0;
                    double az = 0.0;
                    double bx = 0.0;
                    double by = 0.0;
                    double bz = 0.0;
                    if (!mesh_editor_project_screen_brush_vertex_with_projection(
                            *raw_brush,
                            entry_projection,
                            edge_start,
                            ax,
                            ay,
                            depth_mask != nullptr ? &az : nullptr)
                        || !mesh_editor_project_screen_brush_vertex_with_projection(
                            *raw_brush,
                            entry_projection,
                            edge_end,
                            bx,
                            by,
                            depth_mask != nullptr ? &bz : nullptr)) {
                        continue;
                    }
                    const double vx = bx - ax;
                    const double vy = by - ay;
                    const double length_sq = vx * vx + vy * vy;
                    const double t = length_sq <= 1.0e-12
                        ? 0.0
                        : std::clamp(((raw_x - ax) * vx + (raw_y - ay) * vy) / length_sq, 0.0, 1.0);
                    const double hit_x = ax + vx * t;
                    const double hit_y = ay + vy * t;
                    const double distance = std::hypot(raw_x - hit_x, raw_y - hit_y);
                    if (distance > radius_pixels) {
                        continue;
                    }
                    const double hit_depth = az + (bz - az) * t;
                    if (!mesh_editor_screen_brush_depth_visible(depth_mask, hit_x, hit_y, hit_depth)) {
                        continue;
                    }
                    if (edge[1] < edge[0]) {
                        std::swap(edge[0], edge[1]);
                    }
                    edges.insert(edge);
                }
            }
            if (edges.empty()) {
                selection.edges.erase(entry.first);
            }
            continue;
        }
        if (target_mode == "face") {
            if (!has_screen_point) {
                continue;
            }
            std::set<int>& faces = selection.faces[entry.first];
            for (std::size_t face_index = 0; face_index < entry.second.faces.size(); ++face_index) {
                const std::array<int, 3>& face = entry.second.faces[face_index];
                if (face[0] < 0 || face[1] < 0 || face[2] < 0
                    || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                    continue;
                }
                if (has_screen_ray) {
                    double ray_distance = 0.0;
                    if (mesh_editor_ray_intersects_triangle(
                            screen_ray,
                            entry.second.vertices[static_cast<std::size_t>(face[0])],
                            entry.second.vertices[static_cast<std::size_t>(face[1])],
                            entry.second.vertices[static_cast<std::size_t>(face[2])],
                            ray_distance)) {
                        if (depth_mask != nullptr) {
                            const Vec3 hit = add_vec3(screen_ray.origin, scale_vec3(screen_ray.direction, ray_distance));
                            double hit_x = 0.0;
                            double hit_y = 0.0;
                            double hit_depth = 0.0;
                            if (!project_vertex_with_matrix_depth(
                                    entry_projection.world_view_projection,
                                    hit,
                                    entry_projection.viewport_x,
                                    entry_projection.viewport_y,
                                    entry_projection.viewport_width,
                                    entry_projection.viewport_height,
                                    hit_x,
                                    hit_y,
                                    hit_depth)
                                || !mesh_editor_screen_brush_depth_visible(depth_mask, hit_x, hit_y, hit_depth)) {
                                continue;
                            }
                        }
                        faces.insert(static_cast<int>(face_index));
                        continue;
                    }
                }
                double ax = 0.0;
                double ay = 0.0;
                double az = 0.0;
                double bx = 0.0;
                double by = 0.0;
                double bz = 0.0;
                double cx = 0.0;
                double cy = 0.0;
                double cz = 0.0;
                if (!mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_brush,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[0])],
                        ax,
                        ay,
                        depth_mask != nullptr ? &az : nullptr)
                    || !mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_brush,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[1])],
                        bx,
                        by,
                        depth_mask != nullptr ? &bz : nullptr)
                    || !mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_brush,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[2])],
                        cx,
                        cy,
                        depth_mask != nullptr ? &cz : nullptr)) {
                    continue;
                }
                double w0 = 1.0;
                double w1 = 0.0;
                double w2 = 0.0;
                const double distance = mesh_editor_screen_triangle_distance(raw_x, raw_y, ax, ay, bx, by, cx, cy, &w0, &w1, &w2);
                if (distance > radius_pixels) {
                    continue;
                }
                const double hit_depth = w0 * az + w1 * bz + w2 * cz;
                const double centroid_x = (ax + bx + cx) / 3.0;
                const double centroid_y = (ay + by + cy) / 3.0;
                const double centroid_depth = (az + bz + cz) / 3.0;
                if (!mesh_editor_screen_brush_depth_visible(
                        depth_mask,
                        distance <= 0.001 ? raw_x : centroid_x,
                        distance <= 0.001 ? raw_y : centroid_y,
                        distance <= 0.001 ? hit_depth : centroid_depth)) {
                    continue;
                }
                faces.insert(static_cast<int>(face_index));
            }
            if (faces.empty()) {
                selection.faces.erase(entry.first);
            }
            continue;
        }
        const std::map<int, double> weights = screen_brush_vertex_weights_native(
            item,
            entry.second.vertices,
            nullptr,
            falloff,
            raw_brush,
            depth_mask
        );
        if (weights.empty()) {
            continue;
        }
        std::set<int>& vertices = selection.vertices[entry.first];
        for (const auto& weight : weights) {
            vertices.insert(weight.first);
        }
    }
}

bool mesh_editor_screen_region_contains(const JsonValue& region, double screen_x, double screen_y) {
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        return uv_point_in_polygon({screen_x, screen_y}, points);
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return false;
    }
    return screen_x >= std::min(start_x, end_x)
        && screen_x <= std::max(start_x, end_x)
        && screen_y >= std::min(start_y, end_y)
        && screen_y <= std::max(start_y, end_y);
}

double mesh_editor_screen_orientation(const Vec2& a, const Vec2& b, const Vec2& c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

bool mesh_editor_screen_point_on_segment(const Vec2& point, const Vec2& a, const Vec2& b) {
    constexpr double epsilon = 1.0e-9;
    return std::abs(mesh_editor_screen_orientation(a, b, point)) <= epsilon
        && point[0] >= std::min(a[0], b[0]) - epsilon
        && point[0] <= std::max(a[0], b[0]) + epsilon
        && point[1] >= std::min(a[1], b[1]) - epsilon
        && point[1] <= std::max(a[1], b[1]) + epsilon;
}

bool mesh_editor_screen_segments_intersect(const Vec2& a, const Vec2& b, const Vec2& c, const Vec2& d) {
    const double ab_c = mesh_editor_screen_orientation(a, b, c);
    const double ab_d = mesh_editor_screen_orientation(a, b, d);
    const double cd_a = mesh_editor_screen_orientation(c, d, a);
    const double cd_b = mesh_editor_screen_orientation(c, d, b);
    if (((ab_c > 0.0 && ab_d < 0.0) || (ab_c < 0.0 && ab_d > 0.0))
        && ((cd_a > 0.0 && cd_b < 0.0) || (cd_a < 0.0 && cd_b > 0.0))) {
        return true;
    }
    return mesh_editor_screen_point_on_segment(c, a, b)
        || mesh_editor_screen_point_on_segment(d, a, b)
        || mesh_editor_screen_point_on_segment(a, c, d)
        || mesh_editor_screen_point_on_segment(b, c, d);
}

bool mesh_editor_screen_segment_intersection_point(
    const Vec2& a,
    const Vec2& b,
    const Vec2& c,
    const Vec2& d,
    Vec2& out_point
) {
    if (!mesh_editor_screen_segments_intersect(a, b, c, d)) {
        return false;
    }
    constexpr double epsilon = 1.0e-9;
    const double rx = b[0] - a[0];
    const double ry = b[1] - a[1];
    const double sx = d[0] - c[0];
    const double sy = d[1] - c[1];
    const double denom = rx * sy - ry * sx;
    if (std::abs(denom) > epsilon) {
        const double t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / denom;
        out_point = {a[0] + t * rx, a[1] + t * ry};
        return true;
    }
    for (const Vec2& point : {a, b, c, d}) {
        if (mesh_editor_screen_point_on_segment(point, a, b)
            && mesh_editor_screen_point_on_segment(point, c, d)) {
            out_point = point;
            return true;
        }
    }
    out_point = a;
    return true;
}

bool mesh_editor_screen_point_in_triangle(const Vec2& point, const Vec2& a, const Vec2& b, const Vec2& c) {
    constexpr double epsilon = 1.0e-9;
    const double ab = mesh_editor_screen_orientation(a, b, point);
    const double bc = mesh_editor_screen_orientation(b, c, point);
    const double ca = mesh_editor_screen_orientation(c, a, point);
    const bool has_negative = ab < -epsilon || bc < -epsilon || ca < -epsilon;
    const bool has_positive = ab > epsilon || bc > epsilon || ca > epsilon;
    return !(has_negative && has_positive);
}

bool mesh_editor_screen_triangle_depth_at(
    const Vec2& point,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    double& out_depth
) {
    const Vec2 av{a[0], a[1]};
    const Vec2 bv{b[0], b[1]};
    const Vec2 cv{c[0], c[1]};
    const double area = mesh_editor_screen_orientation(av, bv, cv);
    if (std::abs(area) <= 1.0e-12) {
        return false;
    }
    const double w0 = mesh_editor_screen_orientation(bv, cv, point) / area;
    const double w1 = mesh_editor_screen_orientation(cv, av, point) / area;
    const double w2 = mesh_editor_screen_orientation(av, bv, point) / area;
    out_depth = w0 * a[2] + w1 * b[2] + w2 * c[2];
    return std::isfinite(out_depth);
}

std::vector<Vec2> mesh_editor_screen_region_boundary_points(const JsonValue& region) {
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        return points;
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return {};
    }
    const double left = std::min(start_x, end_x);
    const double right = std::max(start_x, end_x);
    const double top = std::min(start_y, end_y);
    const double bottom = std::max(start_y, end_y);
    return {{left, top}, {right, top}, {right, bottom}, {left, bottom}};
}

bool mesh_editor_screen_region_segment_sample(
    const JsonValue& region,
    double ax,
    double ay,
    double bx,
    double by,
    Vec2& out_sample
) {
    if (!std::isfinite(ax) || !std::isfinite(ay) || !std::isfinite(bx) || !std::isfinite(by)) {
        return false;
    }
    if (mesh_editor_screen_region_contains(region, ax, ay)) {
        out_sample = {ax, ay};
        return true;
    }
    if (mesh_editor_screen_region_contains(region, bx, by)) {
        out_sample = {bx, by};
        return true;
    }
    const Vec2 a{ax, ay};
    const Vec2 b{bx, by};
    const std::string mode = lower_ascii(string_or(region.get("mode"), string_or(region.get("selection_mode"), "rectangle")));
    const std::vector<Vec2> points = vec2_array_from_json(region.get("points"));
    if (mode == "lasso" && points.size() >= 3) {
        for (std::size_t index = 0; index < points.size(); ++index) {
            if (mesh_editor_screen_segment_intersection_point(a, b, points[index], points[(index + 1) % points.size()], out_sample)) {
                return true;
            }
        }
        return false;
    }
    const double start_x = number_or(region.get("start_x"), number_or(region.get("x0"), std::numeric_limits<double>::quiet_NaN()));
    const double start_y = number_or(region.get("start_y"), number_or(region.get("y0"), std::numeric_limits<double>::quiet_NaN()));
    const double end_x = number_or(region.get("end_x"), number_or(region.get("x1"), number_or(region.get("x"), std::numeric_limits<double>::quiet_NaN())));
    const double end_y = number_or(region.get("end_y"), number_or(region.get("y1"), number_or(region.get("y"), std::numeric_limits<double>::quiet_NaN())));
    if (!std::isfinite(start_x) || !std::isfinite(start_y) || !std::isfinite(end_x) || !std::isfinite(end_y)) {
        return false;
    }
    const double left = std::min(start_x, end_x);
    const double right = std::max(start_x, end_x);
    const double top = std::min(start_y, end_y);
    const double bottom = std::max(start_y, end_y);
    const Vec2 top_left{left, top};
    const Vec2 top_right{right, top};
    const Vec2 bottom_right{right, bottom};
    const Vec2 bottom_left{left, bottom};
    return mesh_editor_screen_segment_intersection_point(a, b, top_left, top_right, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, top_right, bottom_right, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, bottom_right, bottom_left, out_sample)
        || mesh_editor_screen_segment_intersection_point(a, b, bottom_left, top_left, out_sample);
}

bool mesh_editor_screen_region_segment_intersects(
    const JsonValue& region,
    double ax,
    double ay,
    double bx,
    double by
) {
    Vec2 sample{};
    return mesh_editor_screen_region_segment_sample(region, ax, ay, bx, by, sample);
}

bool mesh_editor_screen_region_triangle_intersects(
    const JsonValue& region,
    const Vec3& a,
    const Vec3& b,
    const Vec3& c,
    Vec3& out_sample
) {
    if (!std::isfinite(a[0]) || !std::isfinite(a[1]) || !std::isfinite(a[2])
        || !std::isfinite(b[0]) || !std::isfinite(b[1]) || !std::isfinite(b[2])
        || !std::isfinite(c[0]) || !std::isfinite(c[1]) || !std::isfinite(c[2])) {
        return false;
    }
    const Vec2 av{a[0], a[1]};
    const Vec2 bv{b[0], b[1]};
    const Vec2 cv{c[0], c[1]};
    if (mesh_editor_screen_region_contains(region, av[0], av[1])) {
        out_sample = a;
        return true;
    }
    if (mesh_editor_screen_region_contains(region, bv[0], bv[1])) {
        out_sample = b;
        return true;
    }
    if (mesh_editor_screen_region_contains(region, cv[0], cv[1])) {
        out_sample = c;
        return true;
    }
    const std::vector<Vec2> points = mesh_editor_screen_region_boundary_points(region);
    for (const Vec2& point : points) {
        if (mesh_editor_screen_point_in_triangle(point, av, bv, cv)) {
            double depth = 0.0;
            if (mesh_editor_screen_triangle_depth_at(point, a, b, c, depth)) {
                out_sample = {point[0], point[1], depth};
                return true;
            }
        }
    }
    if (points.size() < 2) {
        return false;
    }
    const std::array<std::array<Vec2, 2>, 3> triangle_edges{{{av, bv}, {bv, cv}, {cv, av}}};
    for (std::size_t index = 0; index < points.size(); ++index) {
        const Vec2 region_a = points[index];
        const Vec2 region_b = points[(index + 1) % points.size()];
        for (const auto& edge : triangle_edges) {
            Vec2 hit{};
            if (!mesh_editor_screen_segment_intersection_point(region_a, region_b, edge[0], edge[1], hit)) {
                continue;
            }
            double depth = 0.0;
            if (mesh_editor_screen_triangle_depth_at(hit, a, b, c, depth)) {
                out_sample = {hit[0], hit[1], depth};
                return true;
            }
        }
    }
    return false;
}

void mesh_editor_add_screen_region_selection(
    const MeshEditorSession* session,
    const JsonValue* raw_selection,
    MeshEditorSelection& selection
) {
    if (session == nullptr || raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return;
    }
    const JsonValue* raw_region = raw_selection->get("screen_region");
    if (raw_region == nullptr || raw_region->type != JsonValue::Type::Object) {
        return;
    }
    const std::string target_mode = lower_ascii(string_or(
        raw_selection->get("target_mode"),
        string_or(raw_selection->get("selection_target"), string_or(raw_region->get("target_mode"), "vertex"))
    ));
    const std::string depth_mode = lower_ascii(string_or(
        raw_selection->get("selection_depth_mode"),
        string_or(raw_selection->get("depth_mode"), string_or(raw_region->get("selection_depth_mode"), string_or(raw_region->get("depth_mode"), "xray")))
    ));
    const MeshEditorScreenBrushProjection projection = mesh_editor_screen_brush_projection(*raw_region);
    MeshEditorScreenBrushDepthMask depth_mask_storage;
    const MeshEditorScreenBrushDepthMask* depth_mask = nullptr;
    if (depth_mode != "xray") {
        depth_mask_storage = mesh_editor_screen_brush_depth_mask(session, *raw_region);
        if (depth_mask_storage.valid) {
            depth_mask = &depth_mask_storage;
        }
    }
    for (const auto& entry : session->submeshes) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        if (!mesh_editor_screen_brush_submesh_allowed(item, *raw_region)) {
            continue;
        }
        const MeshEditorScreenBrushProjection entry_projection = mesh_editor_projection_for_submesh(projection, entry.first);
        std::set<int> vertices;
        for (std::size_t vertex_index = 0; vertex_index < entry.second.vertices.size(); ++vertex_index) {
            double screen_x = 0.0;
            double screen_y = 0.0;
            double depth_z = 0.0;
            if (!mesh_editor_project_screen_brush_vertex_with_projection(
                    *raw_region,
                    entry_projection,
                    entry.second.vertices[vertex_index],
                    screen_x,
                    screen_y,
                    depth_mask != nullptr ? &depth_z : nullptr)) {
                continue;
            }
            if (!mesh_editor_screen_region_contains(*raw_region, screen_x, screen_y)) {
                continue;
            }
            if (!mesh_editor_screen_brush_depth_visible(depth_mask, screen_x, screen_y, depth_z)) {
                continue;
            }
            vertices.insert(static_cast<int>(vertex_index));
        }
        if (target_mode == "source") {
            bool source_hit = !vertices.empty();
            for (std::size_t face_index = 0; !source_hit && face_index < entry.second.faces.size(); ++face_index) {
                const std::array<int, 3>& face = entry.second.faces[face_index];
                if (face[0] < 0 || face[1] < 0 || face[2] < 0
                    || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                    continue;
                }
                Vec3 projected[3]{};
                bool valid = true;
                for (int corner = 0; corner < 3; ++corner) {
                    if (!mesh_editor_project_screen_brush_vertex_with_projection(
                            *raw_region,
                            entry_projection,
                            entry.second.vertices[static_cast<std::size_t>(face[static_cast<std::size_t>(corner)])],
                            projected[static_cast<std::size_t>(corner)][0],
                            projected[static_cast<std::size_t>(corner)][1],
                            &projected[static_cast<std::size_t>(corner)][2])) {
                        valid = false;
                        break;
                    }
                }
                Vec3 sample{};
                source_hit = valid
                    && mesh_editor_screen_region_triangle_intersects(*raw_region, projected[0], projected[1], projected[2], sample)
                    && mesh_editor_screen_brush_depth_visible(depth_mask, sample[0], sample[1], sample[2]);
            }
            if (source_hit) {
                selection.source_indices.insert(entry.first);
            }
            continue;
        }
        if (target_mode == "face") {
            std::set<int>& faces = selection.faces[entry.first];
            for (std::size_t face_index = 0; face_index < entry.second.faces.size(); ++face_index) {
                const std::array<int, 3>& face = entry.second.faces[face_index];
                if (face[0] < 0 || face[1] < 0 || face[2] < 0
                    || static_cast<std::size_t>(face[0]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[1]) >= entry.second.vertices.size()
                    || static_cast<std::size_t>(face[2]) >= entry.second.vertices.size()) {
                    continue;
                }
                double ax = 0.0;
                double ay = 0.0;
                double az = 0.0;
                double bx = 0.0;
                double by = 0.0;
                double bz = 0.0;
                double cx = 0.0;
                double cy = 0.0;
                double cz = 0.0;
                if (!mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_region,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[0])],
                        ax,
                        ay,
                        depth_mask != nullptr ? &az : nullptr)
                    || !mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_region,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[1])],
                        bx,
                        by,
                        depth_mask != nullptr ? &bz : nullptr)
                    || !mesh_editor_project_screen_brush_vertex_with_projection(
                        *raw_region,
                        entry_projection,
                        entry.second.vertices[static_cast<std::size_t>(face[2])],
                        cx,
                        cy,
                        depth_mask != nullptr ? &cz : nullptr)) {
                    continue;
                }
                Vec3 sample{};
                if (!mesh_editor_screen_region_triangle_intersects(
                        *raw_region,
                        {ax, ay, az},
                        {bx, by, bz},
                        {cx, cy, cz},
                        sample)) {
                    continue;
                }
                if (!mesh_editor_screen_brush_depth_visible(depth_mask, sample[0], sample[1], sample[2])) {
                    continue;
                }
                faces.insert(static_cast<int>(face_index));
            }
            if (faces.empty()) {
                selection.faces.erase(entry.first);
            }
        } else if (target_mode == "edge") {
            std::set<std::array<int, 2>> edges;
            for (const std::array<int, 3>& face : entry.second.faces) {
                const std::array<std::array<int, 2>, 3> face_edges{{
                    {face[0], face[1]},
                    {face[1], face[2]},
                    {face[2], face[0]},
                }};
                for (const std::array<int, 2>& raw_edge : face_edges) {
                    const std::array<int, 2> edge = edge_key(raw_edge[0], raw_edge[1]);
                    if (edges.find(edge) != edges.end()
                        || edge[0] < 0
                        || edge[1] < 0
                        || static_cast<std::size_t>(edge[0]) >= entry.second.vertices.size()
                        || static_cast<std::size_t>(edge[1]) >= entry.second.vertices.size()) {
                        continue;
                    }
                    double ax = 0.0;
                    double ay = 0.0;
                    double az = 0.0;
                    double bx = 0.0;
                    double by = 0.0;
                    double bz = 0.0;
                    if (!mesh_editor_project_screen_brush_vertex_with_projection(
                            *raw_region,
                            entry_projection,
                            entry.second.vertices[static_cast<std::size_t>(edge[0])],
                            ax,
                            ay,
                            depth_mask != nullptr ? &az : nullptr)
                        || !mesh_editor_project_screen_brush_vertex_with_projection(
                            *raw_region,
                            entry_projection,
                            entry.second.vertices[static_cast<std::size_t>(edge[1])],
                            bx,
                            by,
                            depth_mask != nullptr ? &bz : nullptr)) {
                        continue;
                    }
                    Vec2 sample{};
                    if (!mesh_editor_screen_region_segment_sample(*raw_region, ax, ay, bx, by, sample)) {
                        continue;
                    }
                    if (depth_mask != nullptr) {
                        const double dx = bx - ax;
                        const double dy = by - ay;
                        const double length_sq = dx * dx + dy * dy;
                        const double t = length_sq <= 1.0e-12
                            ? 0.0
                            : std::clamp(((sample[0] - ax) * dx + (sample[1] - ay) * dy) / length_sq, 0.0, 1.0);
                        const double sample_depth = az + (bz - az) * t;
                        if (!mesh_editor_screen_brush_depth_visible(depth_mask, sample[0], sample[1], sample_depth)) {
                            continue;
                        }
                    }
                    edges.insert(edge);
                }
            }
            if (!edges.empty()) {
                selection.edges[entry.first] = std::move(edges);
            }
        } else if (!vertices.empty()) {
            selection.vertices[entry.first] = std::move(vertices);
        }
    }
}

MeshEditorSelection mesh_editor_selection_from_json(const JsonValue* raw_selection, const MeshEditorSession* session = nullptr) {
    MeshEditorSelection selection;
    if (raw_selection == nullptr || raw_selection->type != JsonValue::Type::Object) {
        return selection;
    }
    const JsonValue* raw_brush = raw_selection->get("screen_brush");
    const JsonValue* raw_region = raw_selection->get("screen_region");
    const bool projected_screen_selection =
        mesh_editor_has_projection_payload(raw_brush, -1)
        || mesh_editor_has_projection_payload(raw_region, -1);
    if (!projected_screen_selection) {
        mesh_editor_read_index_groups(raw_selection->get("vertices_by_submesh"), "vertices", selection.vertices);
        mesh_editor_read_vertex_weight_groups(raw_selection->get("vertices_by_submesh"), selection.vertex_weights);
        mesh_editor_read_index_groups(raw_selection->get("faces_by_submesh"), "faces", selection.faces);
        mesh_editor_read_edge_groups(raw_selection->get("edges_by_submesh"), selection.edges);
        selection.source_indices = mesh_editor_indices_from_json(raw_selection->get("source_indices"));

        const int submesh_index = int_or(raw_selection->get("submesh_index"), -1);
        if (submesh_index >= 0) {
            const std::set<int> vertices = mesh_editor_indices_from_json(raw_selection->get("vertices"));
            const std::set<int> faces = mesh_editor_indices_from_json(raw_selection->get("faces"));
            const std::set<std::array<int, 2>> edges = mesh_editor_edges_from_json(raw_selection->get("edges"));
            if (!vertices.empty()) selection.vertices[submesh_index] = vertices;
            if (!faces.empty()) selection.faces[submesh_index] = faces;
            if (!edges.empty()) selection.edges[submesh_index] = edges;
        }
    }
    mesh_editor_add_screen_brush_selection(session, raw_selection, selection);
    mesh_editor_add_screen_region_selection(session, raw_selection, selection);
    mesh_editor_prune_vertex_weights_to_selection(selection);
    return selection;
}

std::size_t mesh_editor_selected_vertex_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.vertices) {
        count += entry.second.size();
    }
    return count;
}

std::size_t mesh_editor_selected_edge_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.edges) {
        count += entry.second.size();
    }
    return count;
}

std::size_t mesh_editor_selected_face_count(const MeshEditorSelection& selection) {
    std::size_t count = 0;
    for (const auto& entry : selection.faces) {
        count += entry.second.size();
    }
    return count;
}

bool mesh_editor_selection_empty(const MeshEditorSelection& selection) {
    return selection.source_indices.empty()
        && mesh_editor_selected_vertex_count(selection) == 0
        && mesh_editor_selected_edge_count(selection) == 0
        && mesh_editor_selected_face_count(selection) == 0;
}

bool mesh_editor_is_live_stroke_operation(const std::string& operation) {
    return operation == "brush" || operation == "transform";
}

std::string mesh_editor_stroke_phase_from_json(const JsonValue& root, const JsonValue& edit) {
    std::string phase = lower_ascii(string_or(edit.get("stroke_phase"), string_or(root.get("stroke_phase"), "")));
    if (phase == "finish") {
        return "end";
    }
    return phase;
}

bool mesh_editor_valid_stroke_phase(const std::string& phase) {
    return phase.empty() || phase == "begin" || phase == "update" || phase == "end" || phase == "cancel";
}

std::string mesh_editor_stroke_id_from_json(const JsonValue& root, const JsonValue& edit) {
    return string_or(edit.get("stroke_id"), string_or(root.get("stroke_id"), ""));
}

std::string mesh_editor_tool_from_edit(const JsonValue& edit) {
    return lower_ascii(string_or(edit.get("tool"), string_or(edit.get("mode"), "")));
}

void mesh_editor_write_metrics(std::ostream& out, double cpp_ms, double io_serialization_ms = 0.0) {
    out << "\"metrics\":{\"cpp_ms\":" << cpp_ms
        << ",\"io_serialization_ms\":" << io_serialization_ms
        << ",\"python_apply_ms\":0,\"d3d11_update_ms\":0}";
}

void mesh_editor_write_session_counts(std::ostream& out, const MeshEditorSession& session) {
    std::size_t vertex_count = 0;
    std::size_t face_count = 0;
    for (const auto& entry : session.submeshes) {
        vertex_count += entry.second.vertices.size();
        face_count += entry.second.faces.size();
    }
    out << "\"submesh_count\":" << session.submeshes.size()
        << ",\"vertex_count\":" << vertex_count
        << ",\"face_count\":" << face_count
        << ",\"topology_revision\":" << session.topology_revision
        << ",\"selection_revision\":" << session.selection_revision
        << ",\"edit_revision\":" << session.edit_revision
        << ",\"stroke_revision\":" << session.stroke_revision
        << ",\"active_stroke\":" << (session.active_stroke.active ? "true" : "false")
        << ",\"selected_vertex_count\":" << mesh_editor_selected_vertex_count(session.selection)
        << ",\"selected_edge_count\":" << mesh_editor_selected_edge_count(session.selection)
        << ",\"selected_face_count\":" << mesh_editor_selected_face_count(session.selection);
}

void mesh_editor_write_extra_attrs_field(std::ostream& out, const JsonValue& extra_attrs) {
    if (extra_attrs.type != JsonValue::Type::Object || extra_attrs.object_value.empty()) {
        return;
    }
    out << ",\"extra_attrs\":";
    write_json_value(out, extra_attrs);
}

void mesh_editor_write_submesh_summaries(std::ostream& out, const MeshEditorSession& session) {
    out << "\"submeshes\":[";
    bool wrote = false;
    for (const auto& entry : session.submeshes) {
        if (wrote) {
            out << ',';
        }
        wrote = true;
        const auto selected_sources = session.selection.source_indices.find(entry.first);
        const auto selected_vertices = session.selection.vertices.find(entry.first);
        const auto selected_edges = session.selection.edges.find(entry.first);
        const auto selected_faces = session.selection.faces.find(entry.first);
        out << "{\"index\":" << entry.first
            << ",\"name\":";
        write_escaped(out, entry.second.name);
        out << ",\"material\":";
        write_escaped(out, entry.second.material);
        out << ",\"texture\":";
        write_escaped(out, entry.second.texture);
        mesh_editor_write_extra_attrs_field(out, entry.second.extra_attrs);
        out
            << ",\"vertex_count\":" << entry.second.vertices.size()
            << ",\"face_count\":" << entry.second.faces.size()
            << ",\"uv_count\":" << entry.second.uvs.size()
            << ",\"normal_count\":" << entry.second.normals.size()
            << ",\"tangent_count\":" << entry.second.tangents.size()
            << ",\"selected\":" << (
                selected_sources != session.selection.source_indices.end()
                || selected_vertices != session.selection.vertices.end()
                || selected_edges != session.selection.edges.end()
                || selected_faces != session.selection.faces.end()
                ? "true" : "false"
            )
            << ",\"selected_vertex_count\":" << (
                selected_vertices == session.selection.vertices.end()
                    ? 0
                    : selected_vertices->second.size()
            )
            << ",\"selected_edge_count\":" << (
                selected_edges == session.selection.edges.end()
                    ? 0
                    : selected_edges->second.size()
            )
            << ",\"selected_face_count\":" << (
                selected_faces == session.selection.faces.end()
                    ? 0
                    : selected_faces->second.size()
            )
            << ",\"has_skinning\":" << (
                (!entry.second.bone_indices.empty() || !entry.second.bone_weights.empty()) ? "true" : "false"
            )
            << "}";
    }
    out << "]";
}

const JsonValue* mesh_editor_value_for_submesh(const JsonValue* value, int submesh_index);

JsonValue mesh_editor_apply_root_json(
    const std::string& editor_session_id,
    const std::string& native_session_id,
    const MeshEditorSession& session,
    const JsonValue& edit,
    const std::string& delta_output_dir
) {
    JsonValue root;
    root.type = JsonValue::Type::Object;
    root.object_value["edit"] = edit;
    const JsonValue* mirror_pairs_by_submesh = edit.get("mirror_pairs_by_submesh");
    const JsonValue* source_normals_by_submesh = edit.get("source_normals_by_submesh");

    JsonValue submeshes;
    submeshes.type = JsonValue::Type::Array;
    for (const auto& entry : session.submeshes) {
        JsonValue item;
        item.type = JsonValue::Type::Object;
        item.object_value["index"] = mesh_editor_json_number(entry.first);
        item.object_value["session_id"] = mesh_editor_json_string(native_session_id);
        item.object_value["editor_session_id"] = mesh_editor_json_string(editor_session_id);
        item.object_value["sparse_output"] = mesh_editor_json_bool(true);
        if (session.selection.source_indices.find(entry.first) != session.selection.source_indices.end()) {
            item.object_value["selected_all_vertices"] = mesh_editor_json_bool(true);
            item.object_value["selected_all_faces"] = mesh_editor_json_bool(true);
        }
        if (const JsonValue* mirror_pairs = mesh_editor_value_for_submesh(mirror_pairs_by_submesh, entry.first)) {
            item.object_value["mirror_pairs"] = *mirror_pairs;
        }
        if (const JsonValue* source_normals = mesh_editor_value_for_submesh(source_normals_by_submesh, entry.first)) {
            item.object_value["source_normals_binary"] = *source_normals;
        }
        mesh_editor_add_delta_output_paths(item, delta_output_dir, editor_session_id, entry.first);
        submeshes.array_value.push_back(item);
    }
    root.object_value["submeshes"] = submeshes;
    return root;
}

const JsonValue* mesh_editor_value_for_submesh(const JsonValue* value, int submesh_index) {
    if (value == nullptr) {
        return nullptr;
    }
    if (value->type == JsonValue::Type::Object) {
        return value->get(std::to_string(submesh_index));
    }
    if (value->type == JsonValue::Type::Array) {
        for (const JsonValue& item : value->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), int_or(item.get("submesh_index"), -1));
            if (index == submesh_index) {
                const JsonValue* values = item.get("values");
                return values != nullptr ? values : &item;
            }
        }
    }
    return nullptr;
}

bool mesh_editor_item_targets_normal_operation(const JsonValue& item, const std::string& operation) {
    const int index = int_or(item.get("index"), -1);
    const std::vector<Vec3> vertices = mesh_vertices_from_item(item);
    const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(item, vertices.size());
    if (index < 0 || vertices.empty()) {
        return false;
    }
    if (operation == "copy_normals") {
        return !selected_vertices_from_edit_domains(item, vertices.size(), faces).empty();
    }
    if (faces.empty()) {
        return false;
    }
    return !selected_faces_from_topology_json(item, faces, vertices.size()).empty();
}

JsonValue mesh_editor_filter_root_to_selected_normal_targets(const JsonValue& root, const std::string& operation) {
    JsonValue filtered_root = root;
    JsonValue filtered_submeshes;
    filtered_submeshes.type = JsonValue::Type::Array;
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes != nullptr && submeshes->type == JsonValue::Type::Array) {
        for (const JsonValue& item : submeshes->array_value) {
            if (item.type == JsonValue::Type::Object && mesh_editor_item_targets_normal_operation(item, operation)) {
                filtered_submeshes.array_value.push_back(item);
            }
        }
    }
    filtered_root.object_value["submeshes"] = std::move(filtered_submeshes);
    return filtered_root;
}

void mesh_editor_push_history(std::vector<MeshEditorHistoryEntry>& stack, MeshEditorHistoryEntry entry) {
    stack.push_back(std::move(entry));
    if (stack.size() > 64) {
        stack.erase(stack.begin());
    }
}

void mesh_editor_restore_submeshes(
    MeshEditorSession& session,
    const std::map<int, MeshSessionSubmesh>& submeshes
) {
    for (const auto& entry : submeshes) {
        session.submeshes[entry.first] = entry.second;
    }
}

int mesh_editor_next_submesh_index(const MeshEditorSession& session) {
    int next_index = 0;
    for (const auto& entry : session.submeshes) {
        next_index = std::max(next_index, entry.first + 1);
    }
    return next_index;
}

MeshSessionSubmesh mesh_editor_submesh_from_result(const SubmeshMeshEditResult& result) {
    MeshSessionSubmesh submesh;
    submesh.name = result.name;
    submesh.material = result.material;
    submesh.texture = result.texture;
    submesh.extra_attrs = result.extra_attrs;
    submesh.vertices = result.vertices;
    submesh.faces = result.faces;
    submesh.source_face_indices = result.source_face_indices.size() == result.faces.size()
        ? result.source_face_indices
        : identity_indices(result.faces.size());
    submesh.normals = result.normals.size() == result.vertices.size() ? result.normals : std::vector<Vec3>();
    submesh.uvs = result.preview_uvs.size() == result.vertices.size() ? result.preview_uvs : std::vector<Vec2>();
    submesh.tangents = result.tangents.size() == result.vertices.size() ? result.tangents : std::vector<Vec3>();
    submesh.tangent_signs = result.tangent_signs.size() == result.vertices.size() ? result.tangent_signs : std::vector<double>();
    if (valid_bone_assignments(result.bones) && result.bones.indices.size() == result.vertices.size()) {
        submesh.bone_indices = result.bones.indices;
        submesh.bone_weights = result.bones.weights;
    }
    submesh.source_vertex_map = result.source_vertex_map.size() == result.vertices.size() ? result.source_vertex_map : std::vector<int>();
    submesh.source_vertex_offsets = result.source_vertex_offsets.size() == result.vertices.size() ? result.source_vertex_offsets : std::vector<int>();
    return submesh;
}

SubmeshMeshEditResult mesh_editor_result_from_transform_result(const SubmeshTransformResult& source) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = "transform";
    result.changed_vertices = source.changed_vertices;
    result.changed_positions = source.changed_positions;
    result.before_positions = source.before_positions;
    result.sparse_snapshot_id = source.sparse_snapshot_id;
    result.changed_vertices_path = source.changed_vertices_path;
    result.changed_positions_path = source.changed_positions_path;
    result.before_positions_path = source.before_positions_path;
    result.source_vertex_map = source.source_vertex_map;
    result.sparse = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_transform_results(
    const std::vector<SubmeshTransformResult>& sources
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshTransformResult& source : sources) {
        results.push_back(mesh_editor_result_from_transform_result(source));
    }
    return results;
}

std::string mesh_editor_compact_json(const JsonValue& value) {
    std::ostringstream out;
    write_json_value(out, value);
    return out.str();
}

JsonValue mesh_editor_json_object() {
    JsonValue value;
    value.type = JsonValue::Type::Object;
    return value;
}

bool mesh_editor_json_object_empty(const JsonValue& value) {
    return value.type != JsonValue::Type::Object || value.object_value.empty();
}

JsonValue mesh_editor_extra_attrs_object(const MeshSessionSubmesh& submesh) {
    return submesh.extra_attrs.type == JsonValue::Type::Object ? submesh.extra_attrs : mesh_editor_json_object();
}

bool mesh_editor_extra_attrs_equal(const JsonValue& left, const JsonValue& right) {
    return mesh_editor_compact_json(left.type == JsonValue::Type::Object ? left : mesh_editor_json_object())
        == mesh_editor_compact_json(right.type == JsonValue::Type::Object ? right : mesh_editor_json_object());
}

const std::vector<std::string>& mesh_editor_material_route_attr_names() {
    static const std::vector<std::string> names{
        "cdmw_material_authority_profile",
        "cdmw_material_authority_contract",
        "cdmw_source_material_name",
        "cdmw_target_material_name",
        "cdmw_target_material_slot_index",
        "cdmw_material_slot_kind",
        "cdmw_source_texture_set_key",
        "cdmw_material_route_status",
        "cdmw_material_route_reason",
        "preview_native_material_overrides",
    };
    return names;
}

void mesh_editor_clear_material_route_attrs(JsonValue& extra_attrs) {
    if (extra_attrs.type != JsonValue::Type::Object) {
        extra_attrs = mesh_editor_json_object();
    }
    for (const std::string& name : mesh_editor_material_route_attr_names()) {
        extra_attrs.object_value.erase(name);
    }
}

void mesh_editor_merge_extra_attrs(JsonValue& target, const JsonValue* patch) {
    if (patch == nullptr || patch->type != JsonValue::Type::Object) {
        return;
    }
    if (target.type != JsonValue::Type::Object) {
        target = mesh_editor_json_object();
    }
    for (const auto& entry : patch->object_value) {
        target.object_value[entry.first] = entry.second;
    }
}

bool mesh_editor_material_assign_has_payload(const JsonValue& edit) {
    if (edit.get("material") != nullptr || edit.get("texture") != nullptr) {
        return true;
    }
    const JsonValue* extra_attrs = edit.get("material_extra_attrs");
    return extra_attrs != nullptr && extra_attrs->type == JsonValue::Type::Object && !extra_attrs->object_value.empty();
}

void mesh_editor_apply_material_assign(MeshSessionSubmesh& submesh, const JsonValue& edit) {
    const bool identity_changed = edit.get("material") != nullptr || edit.get("texture") != nullptr;
    if (const JsonValue* material = edit.get("material")) {
        submesh.material = string_or(material, "");
    }
    if (const JsonValue* texture = edit.get("texture")) {
        submesh.texture = string_or(texture, "");
    }
    if (identity_changed) {
        mesh_editor_clear_material_route_attrs(submesh.extra_attrs);
    }
    mesh_editor_merge_extra_attrs(submesh.extra_attrs, edit.get("material_extra_attrs"));
}

void mesh_editor_apply_material_copy(MeshSessionSubmesh& target, const MeshSessionSubmesh& source, int source_index) {
    target.material = source.material;
    target.texture = source.texture;
    target.extra_attrs = mesh_editor_extra_attrs_object(source);
    if (target.extra_attrs.type != JsonValue::Type::Object) {
        target.extra_attrs = mesh_editor_json_object();
    }
    JsonValue source_index_value;
    source_index_value.type = JsonValue::Type::Number;
    source_index_value.number_value = source_index;
    target.extra_attrs.object_value["cdmw_mesh_edit_material_source_submesh_index"] = source_index_value;
}

bool mesh_editor_same_material_metadata(const MeshSessionSubmesh& left, const MeshSessionSubmesh& right) {
    return left.material == right.material
        && left.texture == right.texture
        && mesh_editor_extra_attrs_equal(left.extra_attrs, right.extra_attrs);
}

void mesh_editor_set_material_result_metadata(SubmeshMeshEditResult& result, const MeshSessionSubmesh& submesh) {
    result.name = submesh.name;
    result.material = submesh.material;
    result.texture = submesh.texture;
    result.extra_attrs = mesh_editor_extra_attrs_object(submesh);
    result.material_metadata_changed = true;
}

void mesh_editor_set_result_preview_geometry(SubmeshMeshEditResult& result, const MeshSessionSubmesh& submesh) {
    result.vertices = submesh.vertices;
    result.faces = submesh.faces;
    result.normals = submesh.normals;
    result.preview_uvs = submesh.uvs;
    result.source_vertex_map = submesh.source_vertex_map;
    result.source_face_indices = submesh.source_face_indices;
}

std::set<int> mesh_editor_material_candidate_indices(const MeshEditorSession& session) {
    std::set<int> candidates = session.selection.source_indices;
    for (const auto& entry : session.selection.vertices) {
        candidates.insert(entry.first);
    }
    for (const auto& entry : session.selection.edges) {
        candidates.insert(entry.first);
    }
    for (const auto& entry : session.selection.faces) {
        candidates.insert(entry.first);
    }
    for (auto iter = candidates.begin(); iter != candidates.end();) {
        if (session.submeshes.find(*iter) == session.submeshes.end()) {
            iter = candidates.erase(iter);
        } else {
            ++iter;
        }
    }
    return candidates;
}

bool mesh_editor_material_has_component_selection(const MeshEditorSession& session) {
    return !session.selection.vertices.empty() || !session.selection.edges.empty() || !session.selection.faces.empty();
}

const JsonValue* mesh_editor_submesh_item_from_root(const JsonValue& root, int submesh_index) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        return nullptr;
    }
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type == JsonValue::Type::Object && int_or(item.get("index"), -1) == submesh_index) {
            return &item;
        }
    }
    return nullptr;
}

std::vector<SubmeshMeshEditResult> run_mesh_editor_material_edit(
    const MeshEditorSession& session,
    const JsonValue& edit_root,
    const JsonValue& edit,
    const std::string& operation
) {
    std::vector<SubmeshMeshEditResult> results;
    if (operation == "material_assign" && !mesh_editor_material_assign_has_payload(edit)) {
        return results;
    }
    int source_index = -1;
    MeshSessionSubmesh source_material;
    if (operation == "material_copy") {
        const JsonValue* source_value = edit.get("source_submesh_index");
        if (source_value == nullptr) {
            source_value = edit.get("source_index");
        }
        if (source_value == nullptr || !strict_int_or(source_value, source_index)) {
            return results;
        }
        const auto source_found = session.submeshes.find(source_index);
        if (source_index < 0 || source_found == session.submeshes.end()) {
            return results;
        }
        source_material = source_found->second;
    }

    const std::set<int> candidates = mesh_editor_material_candidate_indices(session);
    if (candidates.empty()) {
        return results;
    }
    const bool has_component_selection = mesh_editor_material_has_component_selection(session);
    for (const int target_index : candidates) {
        const auto target_found = session.submeshes.find(target_index);
        if (target_found == session.submeshes.end()) {
            continue;
        }
        if (operation == "material_copy" && target_index == source_index) {
            continue;
        }
        MeshSessionSubmesh updated = target_found->second;
        if (operation == "material_assign") {
            mesh_editor_apply_material_assign(updated, edit);
        } else {
            mesh_editor_apply_material_copy(updated, source_material, source_index);
        }
        if (mesh_editor_same_material_metadata(target_found->second, updated)) {
            continue;
        }

        const bool source_selected = session.selection.source_indices.find(target_index) != session.selection.source_indices.end();
        const JsonValue* item = mesh_editor_submesh_item_from_root(edit_root, target_index);
        std::set<int> selected_faces;
        if (item != nullptr && !source_selected) {
            const std::vector<Vec3> vertices = mesh_vertices_from_item(*item);
            const std::vector<std::array<int, 3>> faces = mesh_faces_from_item(*item, vertices.size());
            selected_faces = selected_faces_from_topology_json(*item, faces, vertices.size());
            if (has_component_selection && selected_faces.empty()) {
                continue;
            }
            if (!selected_faces.empty() && selected_faces.size() < faces.size()) {
                std::vector<SubmeshMeshEditResult> split_results = run_separate_edit_for_submesh(*item);
                if (split_results.size() != 2) {
                    continue;
                }
                MeshSessionSubmesh source_after = mesh_editor_submesh_from_result(split_results[0]);
                source_after.name = target_found->second.name;
                source_after.material = target_found->second.material;
                source_after.texture = target_found->second.texture;
                source_after.extra_attrs = target_found->second.extra_attrs;
                split_results[0].action = operation;
                split_results[0].name = source_after.name;
                split_results[0].material = source_after.material;
                split_results[0].texture = source_after.texture;
                split_results[0].extra_attrs = source_after.extra_attrs;

                split_results[1].action = operation;
                split_results[1].name_suffix = " material";
                MeshSessionSubmesh append_after = mesh_editor_submesh_from_result(split_results[1]);
                const std::string base_name = target_found->second.name.empty()
                    ? (target_found->second.material.empty() ? std::string("part_") + std::to_string(target_index) : target_found->second.material)
                    : target_found->second.name;
                append_after.name = base_name + split_results[1].name_suffix;
                append_after.material = target_found->second.material;
                append_after.texture = target_found->second.texture;
                append_after.extra_attrs = target_found->second.extra_attrs;
                if (operation == "material_assign") {
                    mesh_editor_apply_material_assign(append_after, edit);
                } else {
                    mesh_editor_apply_material_copy(append_after, source_material, source_index);
                }
                mesh_editor_set_material_result_metadata(split_results[1], append_after);
                results.push_back(std::move(split_results[0]));
                results.push_back(std::move(split_results[1]));
                continue;
            }
        }

        SubmeshMeshEditResult result;
        result.index = target_index;
        result.action = operation;
        mesh_editor_set_material_result_metadata(result, updated);
        mesh_editor_set_result_preview_geometry(result, updated);
        results.push_back(std::move(result));
    }
    return results;
}

SubmeshMeshEditResult mesh_editor_result_from_cleanup_result(
    const SubmeshCleanupResult& source,
    const std::string& action
) {
    SubmeshMeshEditResult result;
    result.index = source.index;
    result.action = action;
    result.vertices = source.vertices;
    result.faces = source.faces;
    result.normals = source.normals;
    result.preview_uvs = source.uvs;
    result.tangents = source.tangents;
    result.tangent_signs = source.tangent_signs;
    result.bones = source.bones;
    result.source_vertex_map = source.source_vertex_map;
    result.source_vertex_offsets = source.source_vertex_offsets;
    result.source_face_indices = identity_indices(source.faces.size());
    result.index_map = source.index_map;
    result.copy_vertex_indices.assign(source.vertices.size(), -1);
    for (std::size_t old_index = 0; old_index < source.index_map.size(); ++old_index) {
        const int new_index = source.index_map[old_index];
        if (new_index >= 0 && static_cast<std::size_t>(new_index) < result.copy_vertex_indices.size()) {
            result.copy_vertex_indices[static_cast<std::size_t>(new_index)] = static_cast<int>(old_index);
        }
    }
    result.removed_vertices = source.removed_vertices;
    result.removed_faces = source.removed_faces;
    result.topology_changed = true;
    return result;
}

std::vector<SubmeshMeshEditResult> mesh_editor_results_from_cleanup_results(
    const std::vector<SubmeshCleanupResult>& sources,
    const std::string& action
) {
    std::vector<SubmeshMeshEditResult> results;
    results.reserve(sources.size());
    for (const SubmeshCleanupResult& source : sources) {
        if (source.index >= 0 && (!source.vertices.empty() || !source.faces.empty())) {
            results.push_back(mesh_editor_result_from_cleanup_result(source, action));
        }
    }
    return results;
}

std::string run_mesh_editor_session(const JsonValue& root) {
    const auto started = std::chrono::steady_clock::now();
    const std::string session_id = string_or(root.get("session_id"), "");
    if (session_id.empty()) {
        throw std::runtime_error("missing mesh editor session_id");
    }
    std::string command = lower_ascii(string_or(root.get("command"), string_or(root.get("operation"), "")));
    if (command.empty()) {
        throw std::runtime_error("missing mesh editor command");
    }
    const std::string native_session_id = mesh_editor_native_session_id(session_id);

    if (command == "open") {
        const JsonValue* submeshes = root.get("submeshes");
        if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
            throw std::runtime_error("missing mesh editor submeshes");
        }
        MeshEditorSession editor_session;
        int stored = 0;
        for (const JsonValue& item : submeshes->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), -1);
            if (index < 0) {
                continue;
            }
            MeshSessionSubmesh submesh = mesh_session_submesh_from_item(item);
            if (submesh.vertices.empty()) {
                continue;
            }
            editor_session.submeshes[index] = std::move(submesh);
            ++stored;
        }
        if (stored <= 0) {
            throw std::runtime_error("mesh editor open stored no submeshes");
        }
        g_mesh_editor_sessions[session_id] = std::move(editor_session);
        g_mesh_sessions[native_session_id] = g_mesh_editor_sessions[session_id].submeshes;

        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"open\",\"session_id\":";
        write_escaped(out, session_id);
        out << ',';
        mesh_editor_write_session_counts(out, g_mesh_editor_sessions[session_id]);
        out << ',';
        mesh_editor_write_submesh_summaries(out, g_mesh_editor_sessions[session_id]);
        out << ',';
        mesh_editor_write_metrics(out, cpp_ms);
        out << "}";
        return out.str();
    }

    if (command == "close") {
        g_mesh_editor_sessions.erase(session_id);
        g_mesh_sessions.erase(native_session_id);
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"close\",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"submesh_count\":0,";
        mesh_editor_write_metrics(out, cpp_ms);
        out << "}";
        return out.str();
    }

    auto found = g_mesh_editor_sessions.find(session_id);
    if (found == g_mesh_editor_sessions.end()) {
        throw std::runtime_error("missing mesh editor session");
    }
    MeshEditorSession& session = found->second;

    if (command == "summary") {
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"summary\",\"session_id\":";
        write_escaped(out, session_id);
        out << ',';
        mesh_editor_write_session_counts(out, session);
        out << ',';
        mesh_editor_write_submesh_summaries(out, session);
        out << ',';
        mesh_editor_write_metrics(out, cpp_ms);
        out << "}";
        return out.str();
    }

    if (command == "select") {
        const JsonValue* raw_selection = root.get("selection");
        std::string selection_operation = string_or(root.get("selection_operation"), string_or(root.get("operation"), ""));
        if (selection_operation.empty() && raw_selection != nullptr) {
            selection_operation = string_or(raw_selection->get("operation"), string_or(raw_selection->get("selection_operation"), "replace"));
        }
        selection_operation = lower_ascii(selection_operation.empty() ? "replace" : selection_operation);
        const MeshEditorSelection incoming = mesh_editor_selection_from_json(raw_selection, &session);
        const bool context_operation = selection_operation == "context";
        const int source_pick_count = context_operation ? static_cast<int>(incoming.source_indices.size()) : -1;
        bool selection_changed = true;
        if (selection_operation == "grow" || selection_operation == "shrink" || selection_operation == "smooth"
            || selection_operation == "all" || selection_operation == "invert") {
            const int iterations = std::max(
                0,
                int_or(root.get("iterations"), raw_selection != nullptr ? int_or(raw_selection->get("iterations"), 1) : 1)
            );
            session.selection = mesh_editor_apply_selection_edit(session, incoming, selection_operation, iterations);
        } else if (context_operation) {
            if (mesh_editor_selection_empty(incoming)) {
                selection_changed = false;
            } else {
                session.selection = mesh_editor_prune_and_combine_selection(session, incoming, "replace");
            }
        } else {
            session.selection = mesh_editor_prune_and_combine_selection(
                session,
                incoming,
                normalized_selection_operation(selection_operation)
            );
        }
        if (selection_changed) {
            ++session.selection_revision;
        }
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        return mesh_editor_select_report_json(
            session,
            session_id,
            selection_operation,
            string_or(root.get("selection_output_dir"), ""),
            cpp_ms,
            source_pick_count
        );
    }

    if (command == "undo" || command == "redo") {
        std::vector<MeshEditorHistoryEntry>& from_stack = command == "undo" ? session.undo_stack : session.redo_stack;
        std::vector<MeshEditorHistoryEntry>& to_stack = command == "undo" ? session.redo_stack : session.undo_stack;
        if (from_stack.empty()) {
            throw std::runtime_error("mesh editor history is empty");
        }
        const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
        const bool include_edit_report = bool_or(root.get("include_edit_report"), !delta_output_dir.empty());
        MeshEditorHistoryEntry entry = std::move(from_stack.back());
        from_stack.pop_back();
        const bool topology_changed = entry.topology_changed;
        const std::map<int, MeshSessionSubmesh>& restored_submeshes = command == "undo" ? entry.before : entry.after;
        const std::set<int>& absent_submeshes = command == "undo" ? entry.absent_before : entry.absent_after;
        const std::string history_operation = entry.operation;
        const bool normal_history = mesh_editor_is_normal_operation(history_operation);
        const bool tangent_history = mesh_editor_is_tangent_operation(history_operation) && !topology_changed;
        const bool uv_history = mesh_editor_is_uv_operation(history_operation) && !topology_changed;
        const bool material_history = history_operation == "material_assign" || history_operation == "material_copy";
        std::vector<SubmeshMeshEditResult> results;
        std::vector<SubmeshNormalsResult> normal_results;
        std::vector<SubmeshTangentsResult> tangent_results;
        std::vector<SubmeshUvTransformResult> uv_results;
        std::set<int> affected_indices;
        std::map<int, MeshSessionSubmesh>& native_session = g_mesh_sessions[native_session_id];
        for (const auto& restored : restored_submeshes) {
            affected_indices.insert(restored.first);
            const auto current_found = session.submeshes.find(restored.first);
            if (current_found != session.submeshes.end()) {
                if (normal_history) {
                    normal_results.push_back(mesh_editor_normal_history_report_result(
                        restored.first,
                        current_found->second,
                        restored.second,
                        history_operation,
                        delta_output_dir,
                        session_id
                    ));
                } else if (uv_history) {
                    uv_results.push_back(mesh_editor_uv_history_report_result(
                        restored.first,
                        current_found->second,
                        restored.second,
                        delta_output_dir,
                        session_id
                    ));
                } else if (tangent_history) {
                    tangent_results.push_back(mesh_editor_tangent_history_report_result(
                        restored.first,
                        current_found->second,
                        restored.second,
                        delta_output_dir,
                        session_id
                    ));
                } else {
                    results.push_back(mesh_editor_history_report_result(
                        restored.first,
                        current_found->second,
                        restored.second,
                        material_history ? history_operation : command,
                        topology_changed,
                        delta_output_dir,
                        session_id
                    ));
                }
            } else {
                SubmeshMeshEditResult appended = mesh_editor_history_report_result(
                    restored.first,
                    MeshSessionSubmesh{},
                    restored.second,
                    material_history ? history_operation : command,
                    true,
                    delta_output_dir,
                    session_id
                );
                appended.append_submesh = true;
                const auto source_found = entry.append_source_indices.find(restored.first);
                appended.source_index = source_found != entry.append_source_indices.end() ? source_found->second : restored.first;
                appended.name_suffix = " restored";
                results.push_back(std::move(appended));
            }
        }
        for (const int index : absent_submeshes) {
            affected_indices.insert(index);
            session.submeshes.erase(index);
            native_session.erase(index);
        }
        mesh_editor_restore_submeshes(session, restored_submeshes);
        for (const auto& restored : restored_submeshes) {
            native_session[restored.first] = restored.second;
        }
        mesh_editor_push_history(to_stack, std::move(entry));
        if (topology_changed) {
            ++session.topology_revision;
            session.selection = MeshEditorSelection{};
            ++session.selection_revision;
        }
        ++session.edit_revision;

        const auto report_started = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
        const std::string edit_report = include_edit_report
            ? (
                normal_history
                    ? normals_report_json(normal_results, history_operation)
                    : (
                        uv_history
                            ? uv_transform_report_json(uv_results)
                            : (tangent_history ? tangents_report_json(tangent_results) : mesh_edit_report_json(results))
                    )
            )
            : std::string();
        const auto report_finished = std::chrono::steady_clock::now();
        const double io_serialization_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":";
        write_escaped(out, command);
        out << ",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"affected_submesh_indices\":[";
        bool wrote = false;
        for (const int index : affected_indices) {
            if (wrote) {
                out << ',';
            }
            wrote = true;
            out << index;
        }
        out << "],\"topology_changed\":" << (topology_changed ? "true" : "false")
            << ",\"result_count\":"
            << (
                normal_history
                    ? normal_results.size()
                    : (uv_history ? uv_results.size() : (tangent_history ? tangent_results.size() : results.size()))
            )
            << ',';
        mesh_editor_write_session_counts(out, session);
        out << ',';
        mesh_editor_write_submesh_summaries(out, session);
        out << ',';
        mesh_editor_write_metrics(out, cpp_ms, io_serialization_ms);
        if (include_edit_report) {
            out << ",\"edit_report\":" << edit_report;
        }
        out << "}";
        return out.str();
    }

    if (command == "export_snapshot") {
        const JsonValue* requested = root.get("submeshes");
        std::ostringstream exported_submeshes;
        bool wrote_exported_submesh = false;
        if (requested != nullptr && requested->type == JsonValue::Type::Array) {
            for (const JsonValue& item : requested->array_value) {
                if (item.type != JsonValue::Type::Object) {
                    continue;
                }
                const int index = int_or(item.get("index"), -1);
                const auto submesh_found = session.submeshes.find(index);
                if (submesh_found == session.submeshes.end()) {
                    continue;
                }
                const MeshSessionSubmesh& submesh = submesh_found->second;
                const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
                const std::string faces_path = string_or(item.get("faces_output_path"), "");
                if (vertices_path.empty() || faces_path.empty()) {
                    const std::string normals_path = string_or(item.get("normals_output_path"), "");
                    const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
                    if (!vertices_path.empty()) write_vec3_binary_file(vertices_path, submesh.vertices);
                    if (!faces_path.empty()) write_faces_binary_file(faces_path, submesh.faces);
                    if (!normals_path.empty()) write_vec3_binary_file(normals_path, submesh.normals);
                    if (!uvs_path.empty()) write_vec2_binary_file(uvs_path, submesh.uvs);
                    continue;
                }
                write_vec3_binary_file(vertices_path, submesh.vertices);
                write_faces_binary_file(faces_path, submesh.faces);
                if (wrote_exported_submesh) {
                    exported_submeshes << ',';
                }
                wrote_exported_submesh = true;
                exported_submeshes << "{\"index\":" << index
                    << ",\"session_id\":";
                write_escaped(exported_submeshes, session_id);
                exported_submeshes << ",\"name\":";
                write_escaped(exported_submeshes, submesh.name);
                exported_submeshes << ",\"material\":";
                write_escaped(exported_submeshes, submesh.material);
                exported_submeshes << ",\"texture\":";
                write_escaped(exported_submeshes, submesh.texture);
                mesh_editor_write_extra_attrs_field(exported_submeshes, submesh.extra_attrs);
                exported_submeshes << ",\"vertex_count\":" << submesh.vertices.size()
                    << ",\"face_count\":" << submesh.faces.size()
                    << ",\"vertices_binary\":";
                write_vec3_binary_descriptor(exported_submeshes, vertices_path, submesh.vertices.size());
                exported_submeshes << ",\"faces_binary\":";
                write_int_binary_descriptor(exported_submeshes, faces_path, submesh.faces.size(), 3);

                const std::string source_faces_path = string_or(item.get("source_face_indices_output_path"), "");
                if (!source_faces_path.empty() && submesh.source_face_indices.size() == submesh.faces.size()) {
                    int source_face_start = -1;
                    if (contiguous_int_range(submesh.source_face_indices, source_face_start)) {
                        exported_submeshes << ",\"source_face_start\":" << source_face_start
                            << ",\"source_face_count\":" << submesh.source_face_indices.size();
                    } else {
                        write_int_binary_file(source_faces_path, submesh.source_face_indices);
                        exported_submeshes << ",\"source_face_indices_binary\":";
                        write_int_binary_descriptor(exported_submeshes, source_faces_path, submesh.source_face_indices.size(), 1);
                    }
                }
                const std::string normals_path = string_or(item.get("normals_output_path"), "");
                if (!normals_path.empty() && submesh.normals.size() == submesh.vertices.size()) {
                    write_vec3_binary_file(normals_path, submesh.normals);
                    exported_submeshes << ",\"normals_binary\":";
                    write_vec3_binary_descriptor(exported_submeshes, normals_path, submesh.normals.size());
                }
                const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
                if (!uvs_path.empty() && submesh.uvs.size() == submesh.vertices.size()) {
                    write_vec2_binary_file(uvs_path, submesh.uvs);
                    exported_submeshes << ",\"uvs_binary\":";
                    write_vec2_binary_descriptor(exported_submeshes, uvs_path, submesh.uvs.size());
                }
                const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
                if (!tangents_path.empty() && submesh.tangents.size() == submesh.vertices.size()) {
                    write_vec3_binary_file(tangents_path, submesh.tangents);
                    exported_submeshes << ",\"tangents_binary\":";
                    write_vec3_binary_descriptor(exported_submeshes, tangents_path, submesh.tangents.size());
                }
                const std::string tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
                if (!tangent_signs_path.empty() && submesh.tangent_signs.size() == submesh.vertices.size()) {
                    write_double_binary_file(tangent_signs_path, submesh.tangent_signs);
                    exported_submeshes << ",\"tangent_signs_binary\":";
                    write_f64_binary_descriptor(exported_submeshes, tangent_signs_path, submesh.tangent_signs.size());
                }
                const std::string bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
                const std::string bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
                const std::string bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
                const BoneAssignments bones{submesh.bone_indices, submesh.bone_weights};
                const std::vector<int> bone_counts = bone_assignment_counts(bones);
                if (!bone_counts_path.empty()
                    && !bone_indices_path.empty()
                    && !bone_weights_path.empty()
                    && valid_bone_assignments(bones)
                    && bone_counts.size() == submesh.vertices.size()) {
                    const std::vector<int> flat_bone_indices = flatten_bone_indices(bones);
                    const std::vector<double> flat_bone_weights = flatten_bone_weights(bones);
                    if (flat_bone_indices.size() == flat_bone_weights.size()) {
                        write_int_binary_file(bone_counts_path, bone_counts);
                        write_int_binary_file(bone_indices_path, flat_bone_indices);
                        write_double_binary_file(bone_weights_path, flat_bone_weights);
                        exported_submeshes << ",\"bone_counts_binary\":";
                        write_int_binary_descriptor(exported_submeshes, bone_counts_path, bone_counts.size(), 1);
                        exported_submeshes << ",\"bone_indices_binary\":";
                        write_int_binary_descriptor(exported_submeshes, bone_indices_path, flat_bone_indices.size(), 1);
                        exported_submeshes << ",\"bone_weights_binary\":";
                        write_f64_binary_descriptor(exported_submeshes, bone_weights_path, flat_bone_weights.size());
                    }
                }
                const std::string source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
                if (!source_vertex_map_path.empty() && submesh.source_vertex_map.size() == submesh.vertices.size()) {
                    int source_vertex_map_start = -1;
                    if (contiguous_int_range(submesh.source_vertex_map, source_vertex_map_start)) {
                        exported_submeshes << ",\"source_vertex_map_start\":" << source_vertex_map_start
                            << ",\"source_vertex_map_count\":" << submesh.source_vertex_map.size();
                    } else {
                        write_int_binary_file(source_vertex_map_path, submesh.source_vertex_map);
                        exported_submeshes << ",\"source_vertex_map_binary\":";
                        write_int_binary_descriptor(exported_submeshes, source_vertex_map_path, submesh.source_vertex_map.size(), 1);
                    }
                }
                const std::string source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
                if (!source_vertex_offsets_path.empty() && submesh.source_vertex_offsets.size() == submesh.vertices.size()) {
                    int source_vertex_offsets_start = -1;
                    int source_vertex_offsets_stride = 0;
                    if (contiguous_int_stride_range(submesh.source_vertex_offsets, source_vertex_offsets_start, source_vertex_offsets_stride)) {
                        exported_submeshes << ",\"source_vertex_offsets_start\":" << source_vertex_offsets_start
                            << ",\"source_vertex_offsets_count\":" << submesh.source_vertex_offsets.size()
                            << ",\"source_vertex_offsets_stride\":" << source_vertex_offsets_stride;
                    } else {
                        write_int_binary_file(source_vertex_offsets_path, submesh.source_vertex_offsets);
                        exported_submeshes << ",\"source_vertex_offsets_binary\":";
                        write_int_binary_descriptor(exported_submeshes, source_vertex_offsets_path, submesh.source_vertex_offsets.size(), 1);
                    }
                }
                exported_submeshes << '}';
            }
        }
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"export_snapshot\",\"session_id\":";
        write_escaped(out, session_id);
        out << ',';
        mesh_editor_write_session_counts(out, session);
        out << ',';
        if (requested != nullptr && requested->type == JsonValue::Type::Array) {
            out << "\"submeshes\":[" << exported_submeshes.str() << ']';
        } else {
            mesh_editor_write_submesh_summaries(out, session);
        }
        out << ',';
        mesh_editor_write_metrics(out, cpp_ms);
        out << "}";
        return out.str();
    }

    if (command == "apply") {
        const JsonValue* edit = root.get("edit");
        if (edit == nullptr || edit->type != JsonValue::Type::Object) {
            throw std::runtime_error("missing mesh editor edit object");
        }
        if (g_mesh_sessions.find(native_session_id) == g_mesh_sessions.end()) {
            g_mesh_sessions[native_session_id] = session.submeshes;
        }
        const std::string delta_output_dir = string_or(root.get("delta_output_dir"), "");
        const bool include_edit_report = bool_or(root.get("include_edit_report"), !delta_output_dir.empty());
        const bool include_preview_deltas = bool_or(root.get("include_preview_deltas"), true);
        const std::string operation = lower_ascii(string_or(edit->get("operation"), string_or(root.get("operation"), "")));
        const std::string stroke_phase = mesh_editor_stroke_phase_from_json(root, *edit);
        if (!mesh_editor_valid_stroke_phase(stroke_phase)) {
            throw std::runtime_error("unsupported mesh editor stroke phase: " + stroke_phase);
        }
        if (!stroke_phase.empty() && !mesh_editor_is_live_stroke_operation(operation)) {
            throw std::runtime_error("mesh editor stroke phase requires brush or transform operation");
        }
        if (root.get("selection") != nullptr) {
            session.selection = mesh_editor_selection_from_json(root.get("selection"), &session);
            ++session.selection_revision;
        }
        std::string stroke_id = mesh_editor_stroke_id_from_json(root, *edit);
        if (stroke_phase == "begin") {
            if (session.active_stroke.active) {
                throw std::runtime_error("mesh editor stroke is already active");
            }
            if (stroke_id.empty()) {
                stroke_id = operation + "-" + std::to_string(session.stroke_revision + 1);
            }
            session.active_stroke = MeshEditorStroke{};
            session.active_stroke.active = true;
            session.active_stroke.stroke_id = stroke_id;
            session.active_stroke.operation = operation;
            session.active_stroke.tool = mesh_editor_tool_from_edit(*edit);
            ++session.stroke_revision;
        } else if (stroke_phase == "update" || stroke_phase == "end" || stroke_phase == "cancel") {
            if (stroke_id.empty() && session.active_stroke.active) {
                stroke_id = session.active_stroke.stroke_id;
            }
            if (!session.active_stroke.active || stroke_id.empty() || session.active_stroke.stroke_id != stroke_id) {
                throw std::runtime_error("mesh editor stroke phase requires matching active stroke");
            }
        }
        std::map<int, MeshSessionSubmesh>& native_session = g_mesh_sessions[native_session_id];
        if (stroke_phase == "cancel") {
            std::set<int> affected_indices;
            std::vector<SubmeshMeshEditResult> results;
            bool topology_changed = false;
            bool cancelled_history = false;
            if (!session.undo_stack.empty() && session.undo_stack.back().stroke_id == stroke_id) {
                MeshEditorHistoryEntry entry = std::move(session.undo_stack.back());
                session.undo_stack.pop_back();
                topology_changed = entry.topology_changed;
                for (const auto& restored : entry.before) {
                    affected_indices.insert(restored.first);
                    const auto current_found = session.submeshes.find(restored.first);
                    if (current_found != session.submeshes.end()) {
                        results.push_back(mesh_editor_history_report_result(
                            restored.first,
                            current_found->second,
                            restored.second,
                            "cancel",
                            topology_changed,
                            delta_output_dir,
                            session_id
                        ));
                    }
                }
                for (const int index : entry.absent_before) {
                    affected_indices.insert(index);
                    session.submeshes.erase(index);
                    native_session.erase(index);
                }
                mesh_editor_restore_submeshes(session, entry.before);
                for (const auto& restored : entry.before) {
                    native_session[restored.first] = restored.second;
                }
                if (topology_changed) {
                    ++session.topology_revision;
                    session.selection = MeshEditorSelection{};
                    ++session.selection_revision;
                }
                ++session.edit_revision;
                cancelled_history = true;
            }
            session.active_stroke = MeshEditorStroke{};
            ++session.stroke_revision;

            const auto report_started = std::chrono::steady_clock::now();
            const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
            const std::string edit_report = include_edit_report ? mesh_edit_report_json(results, include_preview_deltas) : std::string();
            const auto report_finished = std::chrono::steady_clock::now();
            const double io_serialization_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
            std::ostringstream out;
            out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"apply\",\"session_id\":";
            write_escaped(out, session_id);
            out << ",\"affected_submesh_indices\":[";
            bool wrote = false;
            for (const int index : affected_indices) {
                if (wrote) {
                    out << ',';
                }
                wrote = true;
                out << index;
            }
            out << "],\"topology_changed\":" << (topology_changed ? "true" : "false")
                << ",\"result_count\":" << results.size() << ',';
            mesh_editor_write_session_counts(out, session);
            out << ',';
            mesh_editor_write_submesh_summaries(out, session);
            out << ',';
            mesh_editor_write_metrics(out, cpp_ms, io_serialization_ms);
            if (include_edit_report) {
                out << ",\"edit_report\":" << edit_report;
            }
            out << ",\"stroke\":{\"phase\":\"cancel\",\"stroke_id\":";
            write_escaped(out, stroke_id);
            out << ",\"operation\":";
            write_escaped(out, operation);
            out << ",\"active\":false,\"update_count\":0,\"history_cancelled\":"
                << (cancelled_history ? "true" : "false") << "}}";
            return out.str();
        }
        JsonValue edit_root = mesh_editor_apply_root_json(session_id, native_session_id, session, *edit, delta_output_dir);
        MeshEditorHistoryEntry history;
        const bool normal_operation = mesh_editor_is_normal_operation(operation);
        const bool tangent_operation = mesh_editor_is_tangent_operation(operation);
        const bool uv_operation = mesh_editor_is_uv_operation(operation);
        const bool auto_uv_operation = uv_operation && bool_or(edit->get("auto_uv"), false);
        const bool material_operation = operation == "material_assign" || operation == "material_copy";
        const bool cleanup_operation = operation == "remove_doubles";
        const bool delete_parts_operation = operation == "delete" && bool_or(edit->get("delete_parts"), false);
        history.operation = operation;
        history.stroke_id = stroke_id;
        history.stroke_update_count = stroke_phase.empty() ? 0 : 1;
        std::vector<SubmeshMeshEditResult> results;
        std::vector<SubmeshNormalsResult> normal_results;
        std::vector<SubmeshTangentsResult> tangent_results;
        std::vector<SubmeshUvTransformResult> uv_results;
        if (delete_parts_operation) {
            for (const int source_index : session.selection.source_indices) {
                const auto found_submesh = session.submeshes.find(source_index);
                if (found_submesh == session.submeshes.end()) {
                    continue;
                }
                SubmeshMeshEditResult result;
                result.action = "delete";
                result.index = source_index;
                result.removed_vertices = static_cast<int>(found_submesh->second.vertices.size());
                result.removed_faces = static_cast<int>(found_submesh->second.faces.size());
                result.topology_changed = true;
                results.push_back(std::move(result));
            }
        } else if (operation == "transform") {
            edit_root.object_value["operation"] = mesh_editor_json_string("transform");
            edit_root.object_value["transform"] = *edit;
            results = mesh_editor_results_from_transform_results(run_transform(edit_root));
        } else if (normal_operation) {
            edit_root.object_value["operation"] = mesh_editor_json_string(operation);
            std::vector<SubmeshNormalsResult> raw_normal_results =
                run_recalculate_normals(mesh_editor_filter_root_to_selected_normal_targets(edit_root, operation));
            for (SubmeshNormalsResult& normal_result : raw_normal_results) {
                if (mesh_editor_normals_result_changed(normal_result)) {
                    auto native_found = native_session.find(normal_result.index);
                    if (native_found != native_session.end()) {
                        MeshSessionSubmesh& updated = native_found->second;
                        if (normal_result.normals.size() == updated.vertices.size()) {
                            updated.normals = normal_result.normals;
                        }
                        if (!normal_result.faces.empty()) {
                            updated.faces = normal_result.faces;
                        }
                        updated.tangents.clear();
                        updated.tangent_signs.clear();
                    }
                    normal_results.push_back(std::move(normal_result));
                }
            }
            results = mesh_editor_results_from_normals_results(normal_results);
        } else if (uv_operation) {
            if (auto_uv_operation) {
                edit_root.object_value["operation"] = mesh_editor_json_string("auto_uv");
                edit_root.object_value["auto_uv"] = *edit;
                std::vector<SubmeshAutoUvResult> raw_auto_uv_results = run_auto_uv(edit_root);
                for (const SubmeshAutoUvResult& auto_uv_result : raw_auto_uv_results) {
                    if (auto_uv_result.status != "ok") {
                        throw std::runtime_error(
                            auto_uv_result.error.empty()
                                ? "native auto_uv failed"
                                : std::string("native auto_uv failed: ") + auto_uv_result.error
                        );
                    }
                }
                results = mesh_editor_results_from_auto_uv_results(raw_auto_uv_results, native_session);
            } else {
                edit_root.object_value["operation"] = mesh_editor_json_string("uv_transform");
                edit_root.object_value["uv_transform"] = *edit;
                std::vector<SubmeshUvTransformResult> raw_uv_results = run_uv_transform(edit_root);
                for (SubmeshUvTransformResult& uv_result : raw_uv_results) {
                    if (mesh_editor_uv_result_changed(uv_result)) {
                        auto native_found = native_session.find(uv_result.index);
                        if (native_found != native_session.end()) {
                            MeshSessionSubmesh& updated = native_found->second;
                            if (uv_result.clear_uvs) {
                                updated.uvs.clear();
                            } else if (uv_result.uvs.size() == updated.vertices.size()) {
                                updated.uvs = uv_result.uvs;
                            }
                            updated.tangents.clear();
                            updated.tangent_signs.clear();
                        }
                        uv_results.push_back(std::move(uv_result));
                    }
                }
                results = mesh_editor_results_from_uv_results(uv_results);
            }
        } else if (tangent_operation) {
            edit_root.object_value["operation"] = mesh_editor_json_string("generate_tangents");
            std::vector<SubmeshTangentsResult> raw_tangent_results =
                run_generate_tangents(mesh_editor_filter_root_to_selected_normal_targets(edit_root, "recalculate_normals"));
            for (SubmeshTangentsResult& tangent_result : raw_tangent_results) {
                if (mesh_editor_tangents_result_changed(tangent_result)) {
                    auto native_found = native_session.find(tangent_result.index);
                    if (native_found != native_session.end()) {
                        MeshSessionSubmesh& updated = native_found->second;
                        if (tangent_result.clear_tangents) {
                            updated.tangents.clear();
                            updated.tangent_signs.clear();
                        } else if (tangent_result.tangents.size() == updated.vertices.size()) {
                            updated.tangents = tangent_result.tangents;
                            updated.tangent_signs = tangent_result.tangent_signs.size() == updated.vertices.size()
                                ? tangent_result.tangent_signs
                                : std::vector<double>();
                        }
                    }
                    tangent_results.push_back(std::move(tangent_result));
                }
            }
            results = mesh_editor_results_from_tangents_results(tangent_results);
        } else if (material_operation) {
            results = run_mesh_editor_material_edit(session, edit_root, *edit, operation);
        } else if (cleanup_operation) {
            edit_root.object_value["cleanup"] = *edit;
            results = mesh_editor_results_from_cleanup_results(run_cleanup(edit_root), operation);
        } else {
            results = run_mesh_edit(edit_root);
        }
        std::set<int> affected_indices;
        std::set<int> existing_result_indices;
        for (const SubmeshMeshEditResult& result : results) {
            if (result.index < 0) {
                continue;
            }
            history.topology_changed = history.topology_changed || result.topology_changed;
            if (result.append_submesh) {
                continue;
            }
            affected_indices.insert(result.index);
            if (!result.append_submesh) {
                if (!delete_parts_operation) {
                    existing_result_indices.insert(result.index);
                }
                const auto before_found = session.submeshes.find(result.index);
                if (before_found != session.submeshes.end()) {
                    history.before[result.index] = before_found->second;
                }
            }
        }
        if (delete_parts_operation) {
            for (const SubmeshMeshEditResult& result : results) {
                if (result.index < 0) {
                    continue;
                }
                history.absent_after.insert(result.index);
                session.submeshes.erase(result.index);
                native_session.erase(result.index);
            }
        }
        for (SubmeshMeshEditResult& result : results) {
            if (!result.append_submesh || !result.topology_changed || result.vertices.empty() || result.faces.empty()) {
                continue;
            }
            const int source_index = result.source_index >= 0 ? result.source_index : result.index;
            const int appended_index = mesh_editor_next_submesh_index(session);
            result.index = appended_index;
            affected_indices.insert(appended_index);
            history.absent_before.insert(appended_index);
            history.append_source_indices[appended_index] = source_index;
            const auto source_found = session.submeshes.find(source_index);
            if (source_found != session.submeshes.end() && !result.material_metadata_changed) {
                const std::string base_name = source_found->second.name.empty()
                    ? std::string("part_") + std::to_string(source_index)
                    : source_found->second.name;
                result.name = base_name + result.name_suffix;
                result.material = source_found->second.material;
                result.texture = source_found->second.texture;
                result.extra_attrs = source_found->second.extra_attrs;
                result.material_metadata_changed = true;
            }
            MeshSessionSubmesh appended = mesh_editor_submesh_from_result(result);
            session.submeshes[appended_index] = appended;
            native_session[appended_index] = appended;
            history.after[appended_index] = appended;
        }
        bool history_coalesced = false;
        int response_stroke_update_count = 0;
        if (!stroke_phase.empty() && session.active_stroke.active) {
            ++session.active_stroke.update_count;
            response_stroke_update_count = session.active_stroke.update_count;
        }
        if (!affected_indices.empty()) {
            if (material_operation) {
                for (const SubmeshMeshEditResult& result : results) {
                    if (result.append_submesh || result.index < 0) {
                        continue;
                    }
                    MeshSessionSubmesh updated;
                    if (result.topology_changed && !result.vertices.empty()) {
                        updated = mesh_editor_submesh_from_result(result);
                    } else {
                        const auto current_found = session.submeshes.find(result.index);
                        if (current_found == session.submeshes.end()) {
                            continue;
                        }
                        updated = current_found->second;
                    }
                    if (result.material_metadata_changed) {
                        updated.name = result.name;
                        updated.material = result.material;
                        updated.texture = result.texture;
                        updated.extra_attrs = result.extra_attrs;
                    }
                    session.submeshes[result.index] = updated;
                    native_session[result.index] = updated;
                    history.after[result.index] = updated;
                }
            } else {
                for (const int index : existing_result_indices) {
                    const auto after_found = native_session.find(index);
                    if (after_found != native_session.end()) {
                        session.submeshes[index] = after_found->second;
                        history.after[index] = after_found->second;
                    }
                }
                for (SubmeshMeshEditResult& result : results) {
                    if (!result.topology_changed || result.append_submesh || result.material_metadata_changed) {
                        continue;
                    }
                    const auto after_found = session.submeshes.find(result.index);
                    if (after_found == session.submeshes.end()) {
                        continue;
                    }
                    result.name = after_found->second.name;
                    result.material = after_found->second.material;
                    result.texture = after_found->second.texture;
                    result.extra_attrs = after_found->second.extra_attrs;
                    result.material_metadata_changed = true;
                }
            }
            if (!history.stroke_id.empty() && !session.undo_stack.empty()) {
                MeshEditorHistoryEntry& previous = session.undo_stack.back();
                if (previous.stroke_id == history.stroke_id
                    && previous.operation == history.operation
                    && !previous.topology_changed
                    && !history.topology_changed) {
                    for (const auto& before : history.before) {
                        if (previous.before.find(before.first) == previous.before.end()
                            && previous.absent_before.find(before.first) == previous.absent_before.end()) {
                            previous.before[before.first] = before.second;
                        }
                    }
                    for (const int index : history.absent_before) {
                        previous.absent_before.insert(index);
                    }
                    for (const auto& after : history.after) {
                        previous.after[after.first] = after.second;
                    }
                    for (const int index : history.absent_after) {
                        previous.absent_after.insert(index);
                    }
                    for (const auto& appended : history.append_source_indices) {
                        previous.append_source_indices[appended.first] = appended.second;
                    }
                    previous.stroke_update_count += 1;
                    response_stroke_update_count = previous.stroke_update_count;
                    history_coalesced = true;
                }
            }
            if (!history_coalesced) {
                mesh_editor_push_history(session.undo_stack, std::move(history));
            }
            session.redo_stack.clear();
            if (session.undo_stack.back().topology_changed) {
                ++session.topology_revision;
                session.selection = MeshEditorSelection{};
                ++session.selection_revision;
            }
            ++session.edit_revision;
        }
        const bool response_topology_changed =
            !affected_indices.empty() && !session.undo_stack.empty() && session.undo_stack.back().topology_changed;
        bool response_stroke_active = session.active_stroke.active;
        if (stroke_phase == "end") {
            session.active_stroke = MeshEditorStroke{};
            response_stroke_active = false;
            ++session.stroke_revision;
        }

        const auto report_started = std::chrono::steady_clock::now();
        const std::string edit_report = include_edit_report
            ? (
                normal_operation
                    ? normals_report_json(normal_results, operation)
                    : (
                        uv_operation
                            ? (auto_uv_operation ? mesh_edit_report_json(results, include_preview_deltas) : uv_transform_report_json(uv_results))
                            : (tangent_operation ? tangents_report_json(tangent_results) : mesh_edit_report_json(results, include_preview_deltas))
                    )
            )
            : std::string();
        const auto report_finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
        const double io_serialization_ms = std::chrono::duration<double, std::milli>(report_finished - report_started).count();
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":\"apply\",\"session_id\":";
        write_escaped(out, session_id);
        out << ",\"affected_submesh_indices\":[";
        bool wrote = false;
        for (const int index : affected_indices) {
            if (wrote) {
                out << ',';
            }
            wrote = true;
            out << index;
        }
        out << "],\"topology_changed\":" << (response_topology_changed ? "true" : "false")
            << ",\"result_count\":"
            << (
                normal_operation
                    ? normal_results.size()
                    : (uv_operation ? (auto_uv_operation ? results.size() : uv_results.size()) : (tangent_operation ? tangent_results.size() : results.size()))
            )
            << ',';
        mesh_editor_write_session_counts(out, session);
        out << ',';
        mesh_editor_write_submesh_summaries(out, session);
        out << ',';
        mesh_editor_write_metrics(out, cpp_ms, io_serialization_ms);
        if (include_edit_report) {
            out << ",\"edit_report\":" << edit_report;
        }
        if (!stroke_phase.empty()) {
            out << ",\"stroke\":{\"phase\":";
            write_escaped(out, stroke_phase);
            out << ",\"stroke_id\":";
            write_escaped(out, stroke_id);
            out << ",\"operation\":";
            write_escaped(out, operation);
            out << ",\"active\":" << (response_stroke_active ? "true" : "false")
                << ",\"update_count\":" << response_stroke_update_count
                << ",\"history_coalesced\":" << (history_coalesced ? "true" : "false") << "}";
        }
        out << "}";
        return out.str();
    }

    throw std::runtime_error("unsupported mesh editor command: " + command);
}

std::string snapshot_submeshes_report_json(const JsonValue& root) {
    std::string operation = string_or(root.get("operation"), "snapshot_submeshes");
    std::transform(operation.begin(), operation.end(), operation.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    const std::string snapshot_id = string_or(root.get("snapshot_id"), "");
    if (operation == "clear_snapshot") {
        if (!snapshot_id.empty()) {
            g_mesh_snapshots.erase(snapshot_id);
        }
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"clear_snapshot\",\"snapshot_id\":";
        write_escaped(out, snapshot_id);
        out << "}";
        return out.str();
    }
    if (operation == "restore_snapshot") {
        const JsonValue* submeshes = root.get("submeshes");
        if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
            throw std::runtime_error("missing submeshes array");
        }
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"restore_snapshot\"";
        if (!snapshot_id.empty()) {
            out << ",\"snapshot_id\":";
            write_escaped(out, snapshot_id);
        }
        out << ",\"submeshes\":[";
        bool wrote = false;
        int restored = 0;
        int total_vertices = 0;
        int total_faces = 0;
        for (const JsonValue& item : submeshes->array_value) {
            if (item.type != JsonValue::Type::Object) {
                continue;
            }
            const int index = int_or(item.get("index"), -1);
            const std::string session_id = string_or(item.get("session_id"), "");
            const MeshSessionSubmesh* snapshot = mesh_snapshot_submesh_for_item(snapshot_id, item);
            if (index < 0 || session_id.empty() || snapshot == nullptr || snapshot->vertices.empty()) {
                continue;
            }
            g_mesh_sessions[session_id][index] = *snapshot;
            if (wrote) {
                out << ',';
            }
            wrote = true;
            ++restored;
            total_vertices += static_cast<int>(snapshot->vertices.size());
            total_faces += static_cast<int>(snapshot->faces.size());
            out << "{\"index\":" << index
                << ",\"session_id\":";
            write_escaped(out, session_id);
            out << ",\"vertex_count\":" << snapshot->vertices.size()
                << ",\"face_count\":" << snapshot->faces.size() << "}";
        }
        out << "],\"restored_submesh_count\":" << restored
            << ",\"vertex_count\":" << total_vertices
            << ",\"face_count\":" << total_faces << "}";
        return out.str();
    }
    const bool export_snapshot = operation == "export_snapshot";
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":";
    write_escaped(out, export_snapshot ? "export_snapshot" : "snapshot_submeshes");
    if (!snapshot_id.empty()) {
        out << ",\"snapshot_id\":";
        write_escaped(out, snapshot_id);
    }
    out << ",\"submeshes\":[";
    bool wrote = false;
    int stored = 0;
    int total_vertices = 0;
    int total_faces = 0;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        const MeshSessionSubmesh* session = export_snapshot
            ? mesh_snapshot_submesh_for_item(snapshot_id, item)
            : mesh_session_submesh_for_item(item);
        if (index < 0 || session == nullptr || session->vertices.empty()) {
            continue;
        }
        if (!export_snapshot && !snapshot_id.empty()) {
            g_mesh_snapshots[snapshot_id][index] = *session;
        }
        const std::string vertices_path = string_or(item.get("vertices_output_path"), "");
        const std::string faces_path = string_or(item.get("faces_output_path"), "");
        if (vertices_path.empty() || faces_path.empty()) {
            throw std::runtime_error("missing snapshot output paths");
        }
        write_vec3_binary_file(vertices_path, session->vertices);
        write_faces_binary_file(faces_path, session->faces);
        if (wrote) {
            out << ',';
        }
        wrote = true;
        ++stored;
        total_vertices += static_cast<int>(session->vertices.size());
        total_faces += static_cast<int>(session->faces.size());
        out << "{\"index\":" << index
            << ",\"session_id\":";
        write_escaped(out, string_or(item.get("session_id"), ""));
        out << ",\"vertex_count\":" << session->vertices.size()
            << ",\"face_count\":" << session->faces.size()
            << ",\"vertices_binary\":";
        write_vec3_binary_descriptor(out, vertices_path, session->vertices.size());
        out << ",\"faces_binary\":";
        write_int_binary_descriptor(out, faces_path, session->faces.size(), 3);

        const std::string source_faces_path = string_or(item.get("source_face_indices_output_path"), "");
        if (!source_faces_path.empty() && session->source_face_indices.size() == session->faces.size()) {
            int source_face_start = -1;
            if (contiguous_int_range(session->source_face_indices, source_face_start)) {
                out << ",\"source_face_start\":" << source_face_start
                    << ",\"source_face_count\":" << session->source_face_indices.size();
            } else {
                write_int_binary_file(source_faces_path, session->source_face_indices);
                out << ",\"source_face_indices_binary\":";
                write_int_binary_descriptor(out, source_faces_path, session->source_face_indices.size(), 1);
            }
        }
        const std::string normals_path = string_or(item.get("normals_output_path"), "");
        if (!normals_path.empty() && session->normals.size() == session->vertices.size()) {
            write_vec3_binary_file(normals_path, session->normals);
            out << ",\"normals_binary\":";
            write_vec3_binary_descriptor(out, normals_path, session->normals.size());
        }
        const std::string uvs_path = string_or(item.get("uvs_output_path"), "");
        if (!uvs_path.empty() && session->uvs.size() == session->vertices.size()) {
            write_vec2_binary_file(uvs_path, session->uvs);
            out << ",\"uvs_binary\":";
            write_vec2_binary_descriptor(out, uvs_path, session->uvs.size());
        }
        const std::string tangents_path = string_or(item.get("tangents_output_path"), "");
        if (!tangents_path.empty() && session->tangents.size() == session->vertices.size()) {
            write_vec3_binary_file(tangents_path, session->tangents);
            out << ",\"tangents_binary\":";
            write_vec3_binary_descriptor(out, tangents_path, session->tangents.size());
        }
        const std::string tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "");
        if (!tangent_signs_path.empty() && session->tangent_signs.size() == session->vertices.size()) {
            write_double_binary_file(tangent_signs_path, session->tangent_signs);
            out << ",\"tangent_signs_binary\":";
            write_f64_binary_descriptor(out, tangent_signs_path, session->tangent_signs.size());
        }
        const std::string bone_counts_path = string_or(item.get("bone_counts_output_path"), "");
        const std::string bone_indices_path = string_or(item.get("bone_indices_output_path"), "");
        const std::string bone_weights_path = string_or(item.get("bone_weights_output_path"), "");
        const BoneAssignments bones{session->bone_indices, session->bone_weights};
        const std::vector<int> bone_counts = bone_assignment_counts(bones);
        if (!bone_counts_path.empty()
            && !bone_indices_path.empty()
            && !bone_weights_path.empty()
            && valid_bone_assignments(bones)
            && bone_counts.size() == session->vertices.size()) {
            const std::vector<int> flat_bone_indices = flatten_bone_indices(bones);
            const std::vector<double> flat_bone_weights = flatten_bone_weights(bones);
            if (flat_bone_indices.size() == flat_bone_weights.size()) {
                write_int_binary_file(bone_counts_path, bone_counts);
                write_int_binary_file(bone_indices_path, flat_bone_indices);
                write_double_binary_file(bone_weights_path, flat_bone_weights);
                out << ",\"bone_counts_binary\":";
                write_int_binary_descriptor(out, bone_counts_path, bone_counts.size(), 1);
                out << ",\"bone_indices_binary\":";
                write_int_binary_descriptor(out, bone_indices_path, flat_bone_indices.size(), 1);
                out << ",\"bone_weights_binary\":";
                write_f64_binary_descriptor(out, bone_weights_path, flat_bone_weights.size());
            }
        }
        const std::string source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "");
        if (!source_vertex_map_path.empty() && session->source_vertex_map.size() == session->vertices.size()) {
            int source_vertex_map_start = -1;
            if (contiguous_int_range(session->source_vertex_map, source_vertex_map_start)) {
                out << ",\"source_vertex_map_start\":" << source_vertex_map_start
                    << ",\"source_vertex_map_count\":" << session->source_vertex_map.size();
            } else {
                write_int_binary_file(source_vertex_map_path, session->source_vertex_map);
                out << ",\"source_vertex_map_binary\":";
                write_int_binary_descriptor(out, source_vertex_map_path, session->source_vertex_map.size(), 1);
            }
        }
        const std::string source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "");
        if (!source_vertex_offsets_path.empty() && session->source_vertex_offsets.size() == session->vertices.size()) {
            int source_vertex_offsets_start = -1;
            int source_vertex_offsets_stride = 0;
            if (contiguous_int_stride_range(session->source_vertex_offsets, source_vertex_offsets_start, source_vertex_offsets_stride)) {
                out << ",\"source_vertex_offsets_start\":" << source_vertex_offsets_start
                    << ",\"source_vertex_offsets_count\":" << session->source_vertex_offsets.size()
                    << ",\"source_vertex_offsets_stride\":" << source_vertex_offsets_stride;
            } else {
                write_int_binary_file(source_vertex_offsets_path, session->source_vertex_offsets);
                out << ",\"source_vertex_offsets_binary\":";
                write_int_binary_descriptor(out, source_vertex_offsets_path, session->source_vertex_offsets.size(), 1);
            }
        }
        out << "}";
    }
    out << "]";
    if (!snapshot_id.empty()) {
        out << ",\"snapshot_handle\":{\"id\":";
        write_escaped(out, snapshot_id);
        out << ",\"submesh_count\":" << stored
            << ",\"vertex_count\":" << total_vertices
            << ",\"face_count\":" << total_faces << "}";
    }
    out << "}";
    return out.str();
}

int mesh_session_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_mesh_session(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int mesh_editor_session_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_mesh_editor_session(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

std::string mesh_editor_session_json_inline_report(const JsonValue& root, int& exit_code) {
    try {
        exit_code = 0;
        return run_mesh_editor_session(root);
    } catch (const std::exception& exc) {
        exit_code = 2;
        return error_report_json(exc.what());
    }
}

int transform_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, transform_report_json(run_transform(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int restore_vertices_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, transform_report_json(run_restore_vertices(root), "restore_vertices"));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int snapshot_vertices_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        const std::string operation = string_or(root.get("operation"), "");
        if (operation == "clear_sparse_snapshot") {
            const std::string snapshot_id = sparse_snapshot_id_from_root(root);
            if (!snapshot_id.empty()) {
                g_sparse_vertex_snapshots.erase(snapshot_id);
            }
            std::ostringstream out;
            out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"clear_sparse_snapshot\",\"native_sparse_snapshot_id\":";
            write_escaped(out, snapshot_id);
            out << "}";
            write_text_file(report_path, out.str());
            return 0;
        }
        write_text_file(report_path, transform_report_json(run_snapshot_vertices(root), "snapshot_vertices"));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int snapshot_submeshes_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, snapshot_submeshes_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int selection_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        const auto started = std::chrono::steady_clock::now();
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        std::vector<SubmeshSelectionResult> results = run_selection_edit(root);
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        write_text_file(report_path, selection_report_json(results, cpp_ms));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int uv_selection_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, uv_selection_report_json(run_uv_selection(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int uv_summary_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, uv_summary_report_json(run_uv_summary(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int mesh_metadata_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, mesh_metadata_report_json(run_mesh_metadata(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int selection_bounds_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, selection_bounds_report_json(run_selection_bounds(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int selection_preview_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, selection_preview_report_json(run_selection_preview(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int selection_prune_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        const auto started = std::chrono::steady_clock::now();
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        std::vector<SubmeshSelectionPruneResult> results = run_selection_prune(root);
        const auto finished = std::chrono::steady_clock::now();
        const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
        write_text_file(report_path, selection_prune_report_json(results, cpp_ms));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int uv_transform_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, uv_transform_report_json(run_uv_transform(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int auto_uv_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        const JsonValue root = JsonParser(read_text_file(job_path)).parse();
        write_text_file(report_path, auto_uv_report_json(run_auto_uv(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int recalculate_normals_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        const std::string operation = string_or(root.get("operation"), "recalculate_normals");
        write_text_file(report_path, normals_report_json(run_recalculate_normals(root), operation));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int generate_tangents_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, tangents_report_json(run_generate_tangents(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int morph_apply_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, morph_apply_report_json(run_morph_apply(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int morph_post_edit_delta_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, morph_post_edit_delta_report_json(run_morph_post_edit_delta(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int morph_target_delta_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, morph_target_delta_report_json(run_morph_target_delta(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int region_volume_delta_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, region_volume_delta_report_json(run_region_volume_delta(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int static_donor_indices_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, static_donor_indices_report_json(run_static_donor_indices(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int pose_preview_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, pose_preview_report_json(run_pose_preview(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int skin_weights_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, skin_weights_report_json(run_skin_weights(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int obj_export_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, obj_export_report_json(run_obj_export(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int obj_manifest_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, obj_manifest_report_json(run_obj_manifest(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int fbx_geometry_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, fbx_geometry_report_json(run_fbx_geometry(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int fbx_export_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, fbx_export_report_json(run_fbx_export(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int cleanup_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, cleanup_report_json(run_cleanup(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int edit_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, mesh_edit_report_json(run_mesh_edit(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int optimize_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, optimize_report_json(run_optimize(root)));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int import_scene_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, import_scene_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_identity_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_preview_identity(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_model_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_preview_model(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_geometry_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, run_preview_geometry(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_triangle_groups_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, preview_triangle_groups_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_vertex_update_groups_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, preview_vertex_update_groups_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int merge_submeshes_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, merge_submeshes_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int preview_decimate_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, preview_decimate_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int affine_transform_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, affine_transform_report_json(root));
        return 0;
    } catch (const std::exception& exc) {
        try {
            write_text_file(report_path, error_report_json(exc.what()));
        } catch (...) {
        }
        std::cerr << exc.what() << "\n";
        return 2;
    }
}

int mesh_core_json_command(const std::string& command, const std::string& job_path, const std::string& report_path) {
    if (command == "mesh-session-json") return mesh_session_json_command(job_path, report_path);
    if (command == "mesh-editor-session-json") return mesh_editor_session_json_command(job_path, report_path);
    if (command == "transform-json") return transform_json_command(job_path, report_path);
    if (command == "restore-vertices-json") return restore_vertices_json_command(job_path, report_path);
    if (command == "snapshot-vertices-json") return snapshot_vertices_json_command(job_path, report_path);
    if (command == "snapshot-submeshes-json") return snapshot_submeshes_json_command(job_path, report_path);
    if (command == "selection-json") return selection_json_command(job_path, report_path);
    if (command == "uv-selection-json") return uv_selection_json_command(job_path, report_path);
    if (command == "uv-summary-json") return uv_summary_json_command(job_path, report_path);
    if (command == "mesh-metadata-json") return mesh_metadata_json_command(job_path, report_path);
    if (command == "selection-bounds-json") return selection_bounds_json_command(job_path, report_path);
    if (command == "selection-preview-json") return selection_preview_json_command(job_path, report_path);
    if (command == "selection-prune-json") return selection_prune_json_command(job_path, report_path);
    if (command == "uv-transform-json") return uv_transform_json_command(job_path, report_path);
    if (command == "auto-uv-json") return auto_uv_json_command(job_path, report_path);
    if (command == "recalculate-normals-json") return recalculate_normals_json_command(job_path, report_path);
    if (command == "generate-tangents-json") return generate_tangents_json_command(job_path, report_path);
    if (command == "morph-apply-json") return morph_apply_json_command(job_path, report_path);
    if (command == "morph-post-edit-delta-json") return morph_post_edit_delta_json_command(job_path, report_path);
    if (command == "morph-target-delta-json") return morph_target_delta_json_command(job_path, report_path);
    if (command == "region-volume-delta-json") return region_volume_delta_json_command(job_path, report_path);
    if (command == "static-donor-indices-json") return static_donor_indices_json_command(job_path, report_path);
    if (command == "pose-preview-json") return pose_preview_json_command(job_path, report_path);
    if (command == "skin-weights-json") return skin_weights_json_command(job_path, report_path);
    if (command == "obj-export-json") return obj_export_json_command(job_path, report_path);
    if (command == "obj-manifest-json") return obj_manifest_json_command(job_path, report_path);
    if (command == "fbx-geometry-json") return fbx_geometry_json_command(job_path, report_path);
    if (command == "fbx-export-json") return fbx_export_json_command(job_path, report_path);
    if (command == "cleanup-json") return cleanup_json_command(job_path, report_path);
    if (command == "edit-json") return edit_json_command(job_path, report_path);
    if (command == "optimize-json") return optimize_json_command(job_path, report_path);
    if (command == "import-scene-json") return import_scene_json_command(job_path, report_path);
    if (command == "preview-identity-json") return preview_identity_json_command(job_path, report_path);
    if (command == "preview-model-json") return preview_model_json_command(job_path, report_path);
    if (command == "preview-geometry-json") return preview_geometry_json_command(job_path, report_path);
    if (command == "preview-triangle-groups-json") return preview_triangle_groups_json_command(job_path, report_path);
    if (command == "preview-vertex-update-groups-json") return preview_vertex_update_groups_json_command(job_path, report_path);
    if (command == "merge-submeshes-json") return merge_submeshes_json_command(job_path, report_path);
    if (command == "preview-decimate-json") return preview_decimate_json_command(job_path, report_path);
    if (command == "affine-transform-json") return affine_transform_json_command(job_path, report_path);
    return -1;
}

int run_service() {
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            JsonParser parser(line);
            const JsonValue root = parser.parse();
            const std::string command = string_or(root.get("command"), "");
            if (command == "shutdown") {
                std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
                return 0;
            }
            if (command == "ping") {
                std::cout << "{\"event\":\"pong\",\"backend\":\"cdmw_mesh_core_0.1\"}" << std::endl;
                continue;
            }
            const JsonValue* inline_payload = root.get("payload");
            if (command == "mesh-editor-session-json" && inline_payload != nullptr && inline_payload->type == JsonValue::Type::Object) {
                int inline_exit_code = 0;
                const std::string report = mesh_editor_session_json_inline_report(*inline_payload, inline_exit_code);
                std::cout << "{\"status\":\"" << (inline_exit_code == 0 ? "ok" : "error")
                          << "\",\"backend\":\"cdmw_mesh_core_0.1\",\"inline_report\":" << report
                          << ",\"exit_code\":" << inline_exit_code << "}" << std::endl;
                continue;
            }
            const std::string job_path = string_or(root.get("job_path"), "");
            const std::string report_path = string_or(root.get("report_path"), "");
            if (command.empty() || job_path.empty() || report_path.empty()) {
                std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":\"missing command/job_path/report_path\"}" << std::endl;
                continue;
            }
            const int exit_code = mesh_core_json_command(command, job_path, report_path);
            std::cout << "{\"status\":\"" << (exit_code == 0 ? "ok" : "error")
                      << "\",\"backend\":\"cdmw_mesh_core_0.1\",\"report_path\":";
            write_escaped(std::cout, report_path);
            std::cout << ",\"exit_code\":" << exit_code << "}" << std::endl;
        } catch (const std::exception& exc) {
            std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_mesh_core_0.1\",\"message\":";
            write_escaped(std::cout, exc.what());
            std::cout << "}" << std::endl;
        }
    }
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "--version") {
        std::cout << "cdmw-mesh-core 0.1\n";
        return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "--service") {
        return run_service();
    }
    if (argc == 4) {
        const int exit_code = mesh_core_json_command(argv[1], argv[2], argv[3]);
        if (exit_code >= 0) {
            return exit_code;
        }
    }
    std::cerr << "usage: cdmw-mesh-core --service | <mesh-session-json|mesh-editor-session-json|transform-json|restore-vertices-json|snapshot-vertices-json|snapshot-submeshes-json|selection-json|uv-selection-json|uv-summary-json|mesh-metadata-json|selection-bounds-json|selection-preview-json|selection-prune-json|uv-transform-json|auto-uv-json|recalculate-normals-json|generate-tangents-json|morph-apply-json|morph-post-edit-delta-json|morph-target-delta-json|region-volume-delta-json|static-donor-indices-json|pose-preview-json|skin-weights-json|obj-export-json|obj-manifest-json|fbx-geometry-json|fbx-export-json|cleanup-json|edit-json|optimize-json|import-scene-json|preview-identity-json|preview-model-json|preview-geometry-json|preview-triangle-groups-json|preview-vertex-update-groups-json|merge-submeshes-json|preview-decimate-json|affine-transform-json> <job.json> <report.json>\n";
    return 1;
}
