// FBX binary primitives: how to put a node on the wire, not what nodes to write.
//
// The build concatenates every owner into one translation unit in the order
// CMakeLists lists them, so this unit is deliberately placed between
// interchange_01, which defines NativeFbxProperty, and interchange_02, which
// writes the document out of these. It carries no ordinal because that position
// is the point, and a number would only misstate it.
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
