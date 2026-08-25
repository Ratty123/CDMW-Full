// One bone's share of a submesh: which vertices it drives and how strongly.
struct NativeFbxCluster {
    int bone_index = -1;
    std::vector<int> vertex_indices;
    std::vector<double> weights;
};

struct NativeFbxShape {
    std::string name;
    std::vector<int> vertex_indices;
    std::vector<double> vertex_deltas_flat;
};

struct NativeFbxSubmesh {
    std::string name;
    std::string material;
    std::vector<double> vertices_flat;
    std::vector<int> indices_flat;
    std::vector<double> normals_flat;
    std::vector<double> uvs_flat;
    std::vector<NativeFbxCluster> clusters;
    std::vector<NativeFbxShape> shapes;
    int vertex_count = 0;
    int face_count = 0;
};

struct NativeFbxBone {
    int index = -1;
    int parent_index = -1;
    std::string name;
    Vec3 position{0.0, 0.0, 0.0};
    Vec3 rotation{0.0, 0.0, 0.0};
    std::vector<double> bind_matrix;  // 16, row-vector convention; empty when unknown
    double visual_size = 0.02;
};

// Group a submesh's per-vertex influences by bone, which is the shape an FBX
// Cluster wants. Rows are variable width: a vertex carries one to six bones.
std::vector<NativeFbxCluster> native_fbx_clusters_from_bones(
    const BoneAssignments& bones,
    std::size_t vertex_count
) {
    if (bones.indices.size() != vertex_count || bones.weights.size() != vertex_count) {
        return {};
    }
    std::map<int, NativeFbxCluster> by_bone;
    for (std::size_t vertex = 0; vertex < vertex_count; ++vertex) {
        const std::vector<int>& row_indices = bones.indices[vertex];
        const std::vector<double>& row_weights = bones.weights[vertex];
        if (row_indices.size() != row_weights.size()) {
            return {};
        }
        for (std::size_t slot = 0; slot < row_indices.size(); ++slot) {
            const int bone = row_indices[slot];
            const double weight = row_weights[slot];
            if (bone < 0 || !std::isfinite(weight) || weight <= 0.0) {
                continue;
            }
            NativeFbxCluster& cluster = by_bone[bone];
            cluster.bone_index = bone;
            cluster.vertex_indices.push_back(static_cast<int>(vertex));
            cluster.weights.push_back(weight);
        }
    }
    std::vector<NativeFbxCluster> result;
    result.reserve(by_bone.size());
    for (auto& entry : by_bone) {
        result.push_back(std::move(entry.second));
    }
    return result;
}

// Inverse of a rotation-plus-translation matrix held in row-vector form.
std::vector<double> native_fbx_invert_bind(const std::vector<double>& bind) {
    if (bind.size() != 16) {
        return {};
    }
    std::vector<double> result(16, 0.0);
    for (int row = 0; row < 3; ++row) {
        for (int column = 0; column < 3; ++column) {
            result[static_cast<std::size_t>(row * 4 + column)] = bind[static_cast<std::size_t>(column * 4 + row)];
        }
    }
    for (int column = 0; column < 3; ++column) {
        double moved = 0.0;
        for (int k = 0; k < 3; ++k) {
            moved -= bind[static_cast<std::size_t>(12 + k)] * result[static_cast<std::size_t>(k * 4 + column)];
        }
        result[static_cast<std::size_t>(12 + column)] = moved;
    }
    result[15] = 1.0;
    return result;
}

std::vector<double> native_fbx_identity_matrix() {
    std::vector<double> result(16, 0.0);
    result[0] = result[5] = result[10] = result[15] = 1.0;
    return result;
}

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
        // Read the skin only from the explicit payload, never from a stored session:
        // a session holds raw palette slots, and a cluster needs skeleton bone indices.
        submesh.clusters = native_fbx_clusters_from_bones(bone_assignments_from_binary(item), vertices.size());
        const JsonValue* morph_targets = item.get("morph_targets");
        if (morph_targets != nullptr && morph_targets->type == JsonValue::Type::Array) {
            std::set<std::string> seen_shape_names;
            for (const JsonValue& target : morph_targets->array_value) {
                if (target.type != JsonValue::Type::Object) {
                    throw std::runtime_error("FBX morph target must be an object");
                }
                NativeFbxShape shape;
                shape.name = string_or(target.get("name"), "");
                if (shape.name.empty() || !seen_shape_names.insert(shape.name).second) {
                    throw std::runtime_error("FBX morph target name is empty or duplicated");
                }
                const std::vector<Vec3> target_vertices = mesh_vertices_from_item(target);
                if (target_vertices.size() != vertices.size()) {
                    throw std::runtime_error("FBX morph target vertex count mismatch");
                }
                for (std::size_t vertex_index = 0; vertex_index < vertices.size(); ++vertex_index) {
                    const Vec3 delta{
                        (target_vertices[vertex_index][0] - vertices[vertex_index][0]) * scale,
                        (target_vertices[vertex_index][1] - vertices[vertex_index][1]) * scale,
                        (target_vertices[vertex_index][2] - vertices[vertex_index][2]) * scale,
                    };
                    if (std::abs(delta[0]) <= 1e-12 && std::abs(delta[1]) <= 1e-12 && std::abs(delta[2]) <= 1e-12) {
                        continue;
                    }
                    shape.vertex_indices.push_back(static_cast<int>(vertex_index));
                    shape.vertex_deltas_flat.insert(shape.vertex_deltas_flat.end(), delta.begin(), delta.end());
                }
                if (!shape.vertex_indices.empty()) {
                    submesh.shapes.push_back(std::move(shape));
                }
            }
        }
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
        bone.rotation = vec3_or(item.get("rotation"), {0.0, 0.0, 0.0});
        const JsonValue* bind = item.get("bind_matrix");
        if (bind != nullptr && bind->type == JsonValue::Type::Array && bind->array_value.size() == 16) {
            bone.bind_matrix.reserve(16);
            for (const JsonValue& component : bind->array_value) {
                bone.bind_matrix.push_back(number_or(&component, 0.0));
            }
        }
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
    const Vec3 origin{0.0, 0.0, 0.0};
    for (NativeFbxBone& bone : bones) {
        double best_distance = 0.0;
        const auto found_children = children_by_parent.find(bone.index);
        if (found_children != children_by_parent.end()) {
            for (const NativeFbxBone* child : found_children->second) {
                // A child's position is already relative to this bone, so its length is
                // the bone's length. Measuring between the two positions instead compared
                // one local offset against another and sized most bones wrongly.
                const double distance = std::sqrt(distance_squared_vec3(child->position, origin));
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
        // The bind pose has to move with the geometry, so only its translation scales;
        // the rotation must stay a rotation or the inverse-bind stops being one.
        if (bone.bind_matrix.size() == 16) {
            bone.bind_matrix[12] *= scale;
            bone.bind_matrix[13] *= scale;
            bone.bind_matrix[14] *= scale;
        }
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
                    [&bone](std::vector<char>& props_out) {
                        fbx_node(
                            props_out,
                            "P",
                            {
                                fbx_string("Lcl Rotation"),
                                fbx_string("Lcl Rotation"),
                                fbx_string(""),
                                fbx_string("A"),
                                fbx_f64(bone.rotation[0]),
                                fbx_f64(bone.rotation[1]),
                                fbx_f64(bone.rotation[2]),
                            }
                        );
                    },
                }
            );
        },
    }
);
}

// A Skin deformer over the geometry, and one Cluster per bone that drives it.
//
// Transform and TransformLink are what make the bind pose agree with the rest pose:
// TransformLink is the bone's global bind, Transform its inverse times the mesh's
// global transform, which is identity here. Get them inconsistent and the mesh
// arrives pre-deformed.
void write_native_fbx_skin_objects(
    std::vector<char>& objects_out,
    const NativeFbxSubmesh& submesh,
    long long skin_id,
    const std::map<int, long long>& cluster_ids,
    const std::map<int, std::vector<double>>& bone_binds
) {
fbx_node(
    objects_out,
    "Deformer",
    {fbx_i64(skin_id), fbx_string(fbx_object_name(submesh.name, "Deformer")), fbx_string("Skin")},
    {
        [](std::vector<char>& skin_out) { fbx_node(skin_out, "Version", {fbx_i32(101)}); },
        [](std::vector<char>& skin_out) { fbx_node(skin_out, "Link_DeformAcuracy", {fbx_f64(50.0)}); },
    }
);
for (const NativeFbxCluster& cluster : submesh.clusters) {
    const auto id_found = cluster_ids.find(cluster.bone_index);
    if (id_found == cluster_ids.end()) {
        continue;
    }
    const auto bind_found = bone_binds.find(cluster.bone_index);
    const std::vector<double> transform_link =
        bind_found != bone_binds.end() && bind_found->second.size() == 16
            ? bind_found->second
            : native_fbx_identity_matrix();
    const std::vector<double> transform = native_fbx_invert_bind(transform_link);
    fbx_node(
        objects_out,
        "Deformer",
        {
            fbx_i64(id_found->second),
            fbx_string(fbx_object_name(submesh.name + "_" + std::to_string(cluster.bone_index), "SubDeformer")),
            fbx_string("Cluster"),
        },
        {
            [](std::vector<char>& cluster_out) { fbx_node(cluster_out, "Version", {fbx_i32(100)}); },
            [](std::vector<char>& cluster_out) { fbx_node(cluster_out, "UserData", {fbx_string(""), fbx_string("")}); },
            [&cluster](std::vector<char>& cluster_out) { fbx_node(cluster_out, "Indexes", {fbx_i32_array(cluster.vertex_indices)}); },
            [&cluster](std::vector<char>& cluster_out) { fbx_node(cluster_out, "Weights", {fbx_f64_array(cluster.weights)}); },
            [&transform](std::vector<char>& cluster_out) { fbx_node(cluster_out, "Transform", {fbx_f64_array(transform)}); },
            [&transform_link](std::vector<char>& cluster_out) { fbx_node(cluster_out, "TransformLink", {fbx_f64_array(transform_link)}); },
        }
    );
}
}

struct NativeFbxShapeIds {
    long long geometry_id = 0;
    long long channel_id = 0;
};

void write_native_fbx_shape_objects(
    std::vector<char>& objects_out,
    const NativeFbxSubmesh& submesh,
    long long blend_shape_id,
    const std::vector<NativeFbxShapeIds>& shape_ids
);

// Every object id the document refers to, allocated once up front because FBX
// connections name ids that have to exist before either block is written.
struct NativeFbxIds {
    std::vector<long long> mesh_ids;
    std::vector<long long> model_ids;
    std::vector<long long> mat_ids;
    std::map<int, long long> bone_model_ids;
    std::map<int, long long> bone_attr_ids;
    std::map<int, std::vector<double>> bone_binds;
    std::vector<long long> skin_ids;                        // 0 where a submesh has no skin
    std::vector<std::map<int, long long>> cluster_ids;
    std::vector<long long> blend_shape_ids;                 // 0 where a submesh has no shapes
    std::vector<std::vector<NativeFbxShapeIds>> shape_ids;
};

NativeFbxIds assign_native_fbx_ids(
    std::vector<NativeFbxSubmesh>& submeshes,
    const std::vector<NativeFbxBone>& bones
) {
    NativeFbxIds ids;
    ids.mesh_ids.reserve(submeshes.size());
    ids.model_ids.reserve(submeshes.size());
    ids.mat_ids.reserve(submeshes.size());
    long long id_ctr = 3000000000LL;
    const auto uid = [&id_ctr]() -> long long {
        id_ctr += 1;
        return id_ctr;
    };
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        ids.mesh_ids.push_back(uid());
        ids.model_ids.push_back(uid());
        ids.mat_ids.push_back(uid());
    }
    for (const NativeFbxBone& bone : bones) {
        ids.bone_model_ids[bone.index] = uid();
        ids.bone_attr_ids[bone.index] = uid();
    }
    (void)uid();

    for (const NativeFbxBone& bone : bones) {
        if (bone.bind_matrix.size() == 16) {
            ids.bone_binds[bone.index] = bone.bind_matrix;
        }
    }
    // A cluster can only bind to a bone that exists, so drop any influence naming
    // a bone this skeleton does not have rather than emitting a dangling link.
    for (NativeFbxSubmesh& submesh : submeshes) {
        std::vector<NativeFbxCluster> kept;
        kept.reserve(submesh.clusters.size());
        for (NativeFbxCluster& cluster : submesh.clusters) {
            if (ids.bone_model_ids.find(cluster.bone_index) != ids.bone_model_ids.end()) {
                kept.push_back(std::move(cluster));
            }
        }
        submesh.clusters = std::move(kept);
    }

    ids.skin_ids.assign(submeshes.size(), 0);
    ids.cluster_ids.resize(submeshes.size());
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        if (submeshes[index].clusters.empty()) {
            continue;
        }
        ids.skin_ids[index] = uid();
        for (const NativeFbxCluster& cluster : submeshes[index].clusters) {
            ids.cluster_ids[index][cluster.bone_index] = uid();
        }
    }
    ids.blend_shape_ids.assign(submeshes.size(), 0);
    ids.shape_ids.resize(submeshes.size());
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        if (submeshes[index].shapes.empty()) {
            continue;
        }
        ids.blend_shape_ids[index] = uid();
        ids.shape_ids[index].reserve(submeshes[index].shapes.size());
        for (std::size_t shape_index = 0; shape_index < submeshes[index].shapes.size(); ++shape_index) {
            ids.shape_ids[index].push_back(NativeFbxShapeIds{uid(), uid()});
        }
    }
    return ids;
}

void write_native_fbx_preamble(std::vector<char>& out) {
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
                        // Geometry goes out in game units, and a game unit is a metre: a
                        // body measures 1.808 tall. UnitScaleFactor states how many
                        // centimetres one unit is, and an importer divides by it -- Blender
                        // computes global_scale as UnitScaleFactor/100 -- so declaring 1
                        // here claimed centimetres and landed every export at a hundredth
                        // of its size.
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("UnitScaleFactor"), fbx_string("double"), fbx_string("Number"), fbx_string(""), fbx_f64(100.0)}); },
                        [](std::vector<char>& props_out) { fbx_node(props_out, "P", {fbx_string("OriginalUnitScaleFactor"), fbx_string("double"), fbx_string("Number"), fbx_string(""), fbx_f64(100.0)}); },
                    }
                );
            },
        }
    );
}

void write_native_fbx_trailer(std::vector<char>& out) {
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
}

void write_native_fbx_connection_rows(
    std::vector<char>& connections_out,
    const std::vector<NativeFbxSubmesh>& submeshes,
    const std::vector<NativeFbxBone>& bones,
    const NativeFbxIds& ids
) {
    for (std::size_t index = 0; index < submeshes.size(); ++index) {
        fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(ids.model_ids[index]), fbx_i64(0)});
        fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(ids.mesh_ids[index]), fbx_i64(ids.model_ids[index])});
        fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(ids.mat_ids[index]), fbx_i64(ids.model_ids[index])});
        if (ids.blend_shape_ids[index] != 0) {
            fbx_node(
                connections_out,
                "C",
                {fbx_string("OO"), fbx_i64(ids.blend_shape_ids[index]), fbx_i64(ids.mesh_ids[index])}
            );
            for (const NativeFbxShapeIds& shape_ids : ids.shape_ids[index]) {
                fbx_node(
                    connections_out,
                    "C",
                    {fbx_string("OO"), fbx_i64(shape_ids.channel_id), fbx_i64(ids.blend_shape_ids[index])}
                );
                fbx_node(
                    connections_out,
                    "C",
                    {fbx_string("OO"), fbx_i64(shape_ids.geometry_id), fbx_i64(shape_ids.channel_id)}
                );
            }
        }
        if (ids.skin_ids[index] == 0) {
            continue;
        }
        // Skin hangs off the geometry, each cluster off the skin, and each bone off
        // its own cluster. That chain is what an importer walks to find the rig.
        fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(ids.skin_ids[index]), fbx_i64(ids.mesh_ids[index])});
        for (const NativeFbxCluster& cluster : submeshes[index].clusters) {
            const auto cluster_found = ids.cluster_ids[index].find(cluster.bone_index);
            const auto bone_found = ids.bone_model_ids.find(cluster.bone_index);
            if (cluster_found == ids.cluster_ids[index].end() || bone_found == ids.bone_model_ids.end()) {
                continue;
            }
            fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(cluster_found->second), fbx_i64(ids.skin_ids[index])});
            fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(bone_found->second), fbx_i64(cluster_found->second)});
        }
    }
    for (const NativeFbxBone& bone : bones) {
        const auto attr_found = ids.bone_attr_ids.find(bone.index);
        const auto model_found = ids.bone_model_ids.find(bone.index);
        if (attr_found == ids.bone_attr_ids.end() || model_found == ids.bone_model_ids.end()) {
            continue;
        }
        fbx_node(connections_out, "C", {fbx_string("OO"), fbx_i64(attr_found->second), fbx_i64(model_found->second)});
        const auto parent_model = ids.bone_model_ids.find(bone.parent_index);
        fbx_node(
            connections_out,
            "C",
            {
                fbx_string("OO"),
                fbx_i64(model_found->second),
                fbx_i64(parent_model != ids.bone_model_ids.end() ? parent_model->second : 0),
            }
        );
    }
}

FbxExportResult run_fbx_export(const JsonValue& root) {
    const std::string output_path = string_or(root.get("output_path"), "");
    if (output_path.empty()) {
        throw std::runtime_error("missing output_path");
    }
    std::vector<NativeFbxSubmesh> submeshes = native_fbx_submeshes_from_json(root);
    std::vector<NativeFbxBone> bones = native_fbx_bones_from_json(root);
    const NativeFbxIds ids = assign_native_fbx_ids(submeshes, bones);

    std::vector<char> out;
    write_native_fbx_preamble(out);

    fbx_node(
        out,
        "Objects",
        {},
        {
            [&submeshes, &bones, &ids](std::vector<char>& objects_out) {
                for (std::size_t index = 0; index < submeshes.size(); ++index) {
                    write_native_fbx_submesh_object(
                        objects_out, submeshes[index], ids.mesh_ids[index], ids.model_ids[index], ids.mat_ids[index]
                    );
                }
                for (const NativeFbxBone& bone : bones) {
                    write_native_fbx_bone_object(objects_out, bone, ids.bone_model_ids, ids.bone_attr_ids);
                }
                for (std::size_t index = 0; index < submeshes.size(); ++index) {
                    if (ids.skin_ids[index] != 0) {
                        write_native_fbx_skin_objects(
                            objects_out, submeshes[index], ids.skin_ids[index], ids.cluster_ids[index], ids.bone_binds
                        );
                    }
                    write_native_fbx_shape_objects(
                        objects_out,
                        submeshes[index],
                        ids.blend_shape_ids[index],
                        ids.shape_ids[index]
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
            [&submeshes, &bones, &ids](std::vector<char>& connections_out) {
                write_native_fbx_connection_rows(connections_out, submeshes, bones, ids);
            },
        }
    );

    write_native_fbx_trailer(out);
    write_binary_file(output_path, out, false);

    FbxExportResult result;
    result.output_path = output_path;
    result.submesh_count = static_cast<int>(submeshes.size());
    for (const NativeFbxSubmesh& submesh : submeshes) {
        result.vertex_count += submesh.vertex_count;
        result.face_count += submesh.face_count;
        result.morph_target_count += static_cast<int>(submesh.shapes.size());
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
