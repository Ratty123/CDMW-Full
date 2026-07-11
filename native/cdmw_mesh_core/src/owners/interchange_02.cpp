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

void write_native_fbx_submesh_object(
    std::vector<char>& objects_out,
    const NativeFbxSubmesh& submesh,
    long long mesh_id,
    long long model_id,
    long long material_id
) {
fbx_node(
    objects_out,
    "Geometry",
    {fbx_i64(mesh_id), fbx_string(fbx_object_name(submesh.name, "Geometry")), fbx_string("Mesh")},
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
    {fbx_i64(model_id), fbx_string(fbx_object_name(submesh.name, "Model")), fbx_string("Mesh")},
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
    {fbx_i64(material_id), fbx_string(fbx_object_name(submesh.material, "Material")), fbx_string("")},
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

void write_native_fbx_bone_object(
    std::vector<char>& objects_out,
    const NativeFbxBone& bone,
    const std::map<int, long long>& bone_model_ids,
    const std::map<int, long long>& bone_attr_ids
) {
const auto attr_found = bone_attr_ids.find(bone.index);
const auto model_found = bone_model_ids.find(bone.index);
if (attr_found == bone_attr_ids.end() || model_found == bone_model_ids.end()) {
    return;
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
                    write_native_fbx_submesh_object(
                        objects_out, submeshes[index], mesh_ids[index], model_ids[index], mat_ids[index]
                    );
                }
                for (const NativeFbxBone& bone : bones) {
                    write_native_fbx_bone_object(objects_out, bone, bone_model_ids, bone_attr_ids);
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
