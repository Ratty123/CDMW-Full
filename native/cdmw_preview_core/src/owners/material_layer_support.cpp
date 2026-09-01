
// Crimson's `_ma` and `_mg` textures select colour/detail layers. They remain
// useful to the material-layer compiler, but their channels are not a global
// roughness/metalness response. Keep this independent of the broad `material`
// role because legacy sidecars classified selectors and surface maps alike.
static bool parameter_is_skin_detail_support(const std::string& parameter_name) {
    const std::string parameter = normalized_key(parameter_name);
    return parameter == "skindetailmasktexture"
        || parameter == "skindetailnormaltexture"
        || parameter == "skindetailmaterialtexture";
}

static bool binding_is_skin_detail_support(const TextureBinding& binding) {
    return parameter_is_skin_detail_support(binding.parameter_name);
}

static bool binding_is_layer_selector_mask(const TextureBinding& binding) {
    const std::string parameter = normalized_key(binding.parameter_name);
    if (parameter == "colorblendingmasktexture"
        || parameter == "detailmasktexture"
        || parameter == "skindetailmasktexture") {
        return true;
    }
    const std::string packed = lower_copy(binding.packed_channels);
    if (packed.find("layer:color_blending_mask") != std::string::npos
        || packed.find("layer:detail_grime_dye_mask") != std::string::npos) {
        return true;
    }
    if (lower_copy(binding.semantic_type) == "detail_mask"
        || lower_copy(binding.semantic_subtype) == "detail_mask") {
        return true;
    }
    const auto selector_suffix = [](const std::string& value) {
        const std::string lower = lower_copy(value);
        return lower.ends_with("_ma.dds") || lower.ends_with("_mg.dds");
    };
    return selector_suffix(binding.archive_path)
        || selector_suffix(binding.texture_name)
        || selector_suffix(binding.source_path);
}
