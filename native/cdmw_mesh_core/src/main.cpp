#include <array>
#include <cerrno>
#include <climits>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

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
    double snap = 0.0;
};

struct UvTransform {
    Vec2 offset{0.0, 0.0};
    Vec2 scale{1.0, 1.0};
    double rotate = 0.0;
    bool flip_u = false;
    bool flip_v = false;
    Vec2 pivot{0.0, 0.0};
};

struct SubmeshTransformResult {
    int index = -1;
    std::vector<Vec3> vertices;
    std::vector<int> changed_vertices;
};

struct SubmeshUvTransformResult {
    int index = -1;
    std::vector<Vec2> uvs;
    std::vector<int> changed_vertices;
};

struct SubmeshNormalsResult {
    int index = -1;
    std::vector<Vec3> normals;
};

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

bool bool_or(const JsonValue* value, bool fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Bool) {
        return fallback;
    }
    return value->bool_value;
}

Vec3 vec3_or(const JsonValue* value, const Vec3& fallback) {
    if (value == nullptr || value->type != JsonValue::Type::Array || value->array_value.size() < 3) {
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

std::set<int> selected_vertices_from_json(const JsonValue* value, std::size_t vertex_count) {
    std::set<int> result;
    if (value == nullptr || value->type != JsonValue::Type::Array) {
        return result;
    }
    for (const JsonValue& item : value->array_value) {
        if (item.type != JsonValue::Type::Number) {
            continue;
        }
        const int index = static_cast<int>(item.number_value);
        if (index >= 0 && static_cast<std::size_t>(index) < vertex_count) {
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
        const int a = int_or(&item.array_value[0], -1);
        const int b = int_or(&item.array_value[1], -1);
        const int c = int_or(&item.array_value[2], -1);
        if (a >= 0 && b >= 0 && c >= 0
            && static_cast<std::size_t>(a) < vertex_count
            && static_cast<std::size_t>(b) < vertex_count
            && static_cast<std::size_t>(c) < vertex_count) {
            result.push_back({a, b, c});
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
    result.translate = vec3_or(transform->get("translate"), result.translate);
    result.scale = vec3_or(transform->get("scale"), result.scale);
    result.rotate = vec3_or(transform->get("rotate"), result.rotate);
    result.pivot = vec3_or(transform->get("pivot"), result.pivot);
    result.snap = std::max(0.0, number_or(transform->get("snap"), 0.0));
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

std::vector<SubmeshTransformResult> run_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const Transform transform = transform_from_json(root);
    std::vector<SubmeshTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.vertices = vertices_from_json(item.get("vertices"));
        const std::set<int> selected = selected_vertices_from_json(item.get("selected_vertices"), result.vertices.size());
        if (result.index < 0 || result.vertices.empty() || selected.empty()) {
            continue;
        }
        for (const int vertex_index : selected) {
            const Vec3 old_vertex = result.vertices[static_cast<std::size_t>(vertex_index)];
            const Vec3 new_vertex = transform_vertex(old_vertex, transform);
            if (!same_vec3(old_vertex, new_vertex)) {
                result.vertices[static_cast<std::size_t>(vertex_index)] = new_vertex;
                result.changed_vertices.push_back(vertex_index);
            }
        }
        if (!result.changed_vertices.empty()) {
            results.push_back(std::move(result));
        }
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

std::vector<SubmeshUvTransformResult> run_uv_transform(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    const UvTransform transform = uv_transform_from_json(root);
    std::vector<SubmeshUvTransformResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        SubmeshUvTransformResult result;
        result.index = int_or(item.get("index"), -1);
        result.uvs = uvs_from_json(item.get("uvs"));
        const int vertex_count = int_or(item.get("vertex_count"), static_cast<int>(result.uvs.size()));
        if (result.index < 0 || result.uvs.empty() || vertex_count < 0 || static_cast<std::size_t>(vertex_count) != result.uvs.size()) {
            continue;
        }
        const std::set<int> selected = selected_vertices_from_json(item.get("selected_vertices"), result.uvs.size());
        if (selected.empty()) {
            continue;
        }
        for (const int vertex_index : selected) {
            const Vec2 old_uv = result.uvs[static_cast<std::size_t>(vertex_index)];
            const Vec2 new_uv = transform_uv(old_uv, transform);
            if (!same_vec2(old_uv, new_uv)) {
                result.uvs[static_cast<std::size_t>(vertex_index)] = new_uv;
                result.changed_vertices.push_back(vertex_index);
            }
        }
        if (!result.changed_vertices.empty()) {
            results.push_back(std::move(result));
        }
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

std::vector<SubmeshNormalsResult> run_recalculate_normals(const JsonValue& root) {
    const JsonValue* submeshes = root.get("submeshes");
    if (submeshes == nullptr || submeshes->type != JsonValue::Type::Array) {
        throw std::runtime_error("missing submeshes array");
    }
    std::vector<SubmeshNormalsResult> results;
    for (const JsonValue& item : submeshes->array_value) {
        if (item.type != JsonValue::Type::Object) {
            continue;
        }
        const int index = int_or(item.get("index"), -1);
        std::vector<Vec3> vertices = vertices_from_json(item.get("vertices"));
        std::vector<std::array<int, 3>> faces = faces_from_json(item.get("faces"), vertices.size());
        if (index < 0 || vertices.empty() || faces.empty()) {
            continue;
        }
        SubmeshNormalsResult result;
        result.index = index;
        result.normals = compute_smooth_normals(vertices, faces);
        results.push_back(std::move(result));
    }
    return results;
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

std::string transform_report_json(const std::vector<SubmeshTransformResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"transform\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshTransformResult& result = results[i];
        out << "{\"index\":" << result.index << ",\"changed_vertices\":[";
        for (std::size_t j = 0; j < result.changed_vertices.size(); ++j) {
            if (j) {
                out << ',';
            }
            out << result.changed_vertices[j];
        }
        out << "],\"vertices\":[";
        for (std::size_t j = 0; j < result.vertices.size(); ++j) {
            if (j) {
                out << ',';
            }
            write_vec3(out, result.vertices[j]);
        }
        out << "]}";
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
        out << "{\"index\":" << result.index << ",\"changed_vertices\":[";
        for (std::size_t j = 0; j < result.changed_vertices.size(); ++j) {
            if (j) {
                out << ',';
            }
            out << result.changed_vertices[j];
        }
        out << "],\"uvs\":[";
        for (std::size_t j = 0; j < result.uvs.size(); ++j) {
            if (j) {
                out << ',';
            }
            write_vec2(out, result.uvs[j]);
        }
        out << "]}";
    }
    out << "]}";
    return out.str();
}

std::string normals_report_json(const std::vector<SubmeshNormalsResult>& results) {
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"operation\":\"recalculate_normals\",\"submeshes\":[";
    for (std::size_t i = 0; i < results.size(); ++i) {
        if (i) {
            out << ',';
        }
        const SubmeshNormalsResult& result = results[i];
        out << "{\"index\":" << result.index << ",\"normals\":[";
        for (std::size_t j = 0; j < result.normals.size(); ++j) {
            if (j) {
                out << ',';
            }
            write_vec3(out, result.normals[j]);
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

int recalculate_normals_json_command(const std::string& job_path, const std::string& report_path) {
    try {
        JsonParser parser(read_text_file(job_path));
        const JsonValue root = parser.parse();
        write_text_file(report_path, normals_report_json(run_recalculate_normals(root)));
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

} // namespace

int main(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "--version") {
        std::cout << "cdmw-mesh-core 0.1\n";
        return 0;
    }
    if (argc == 4 && std::string(argv[1]) == "transform-json") {
        return transform_json_command(argv[2], argv[3]);
    }
    if (argc == 4 && std::string(argv[1]) == "uv-transform-json") {
        return uv_transform_json_command(argv[2], argv[3]);
    }
    if (argc == 4 && std::string(argv[1]) == "recalculate-normals-json") {
        return recalculate_normals_json_command(argv[2], argv[3]);
    }
    std::cerr << "usage: cdmw-mesh-core <transform-json|uv-transform-json|recalculate-normals-json> <job.json> <report.json>\n";
    return 1;
}
