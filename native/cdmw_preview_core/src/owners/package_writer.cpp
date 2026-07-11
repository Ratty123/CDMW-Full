static void emit_package_batch(PackageWriteState& state, size_t batch_index) {
    if (state.submeshes[batch_index].indices.size() < 3) return;
    PackageBatchState batch = start_package_batch(state, batch_index);
    select_package_batch_bindings(state, batch);
    prepare_package_batch_runtime(state, batch);
    prepare_package_batch_material(state, batch);
    record_package_batch_selection(state, batch);
    append_package_material_slot_and_decision(state, batch);
    append_package_batch_json(state, batch);
}

static NativePackage write_d3d11_package(
    const EntryJob& job,
    const std::vector<NativeSubmesh>& submeshes,
    const std::vector<TextureBinding>& bindings,
    NativePackage package
) {
    if (submeshes.empty()) throw std::runtime_error("native package writer received no submeshes");
    PackageWriteState state = start_package_write(job, submeshes, bindings, std::move(package));
    for (size_t batch_index = 0; batch_index < submeshes.size(); ++batch_index) {
        emit_package_batch(state, batch_index);
    }
    return finish_package_write(std::move(state));
}
