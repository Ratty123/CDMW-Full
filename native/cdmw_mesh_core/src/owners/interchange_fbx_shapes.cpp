// Blender-compatible FBX shape objects. The surrounding FBX data types and
// node primitives are defined by the preceding interchange unity owners.

void write_native_fbx_shape_objects(
    std::vector<char>& objects_out,
    const NativeFbxSubmesh& submesh,
    long long blend_shape_id,
    const std::vector<NativeFbxShapeIds>& shape_ids
) {
    if (blend_shape_id == 0 || shape_ids.size() != submesh.shapes.size()) {
        return;
    }
    fbx_node(
        objects_out,
        "Deformer",
        {
            fbx_i64(blend_shape_id),
            fbx_string(fbx_object_name(submesh.name + "_BlendShape", "Deformer")),
            fbx_string("BlendShape"),
        },
        {
            [](std::vector<char>& blend_out) { fbx_node(blend_out, "Version", {fbx_i32(100)}); },
        }
    );
    for (std::size_t index = 0; index < submesh.shapes.size(); ++index) {
        const NativeFbxShape& shape = submesh.shapes[index];
        const NativeFbxShapeIds& ids = shape_ids[index];
        fbx_node(
            objects_out,
            "Geometry",
            {
                fbx_i64(ids.geometry_id),
                fbx_string(fbx_object_name(shape.name, "Geometry")),
                fbx_string("Shape"),
            },
            {
                [](std::vector<char>& shape_out) { fbx_node(shape_out, "Version", {fbx_i32(100)}); },
                [&shape](std::vector<char>& shape_out) { fbx_node(shape_out, "Indexes", {fbx_i32_array(shape.vertex_indices)}); },
                [&shape](std::vector<char>& shape_out) { fbx_node(shape_out, "Vertices", {fbx_f64_array(shape.vertex_deltas_flat)}); },
            }
        );
        fbx_node(
            objects_out,
            "Deformer",
            {
                fbx_i64(ids.channel_id),
                fbx_string(fbx_object_name(shape.name, "SubDeformer")),
                fbx_string("BlendShapeChannel"),
            },
            {
                [](std::vector<char>& channel_out) { fbx_node(channel_out, "Version", {fbx_i32(100)}); },
                [](std::vector<char>& channel_out) { fbx_node(channel_out, "DeformPercent", {fbx_f64(0.0)}); },
                [](std::vector<char>& channel_out) { fbx_node(channel_out, "FullWeights", {fbx_f64_array({100.0})}); },
            }
        );
    }
}
