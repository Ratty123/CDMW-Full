std::string mesh_editor_snapshot_normalized_path(std::string path) {
    for (char& ch : path) {
        if (ch == '\\') ch = '/';
        else ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
    }
    while (path.size() > 1 && path.back() == '/') path.pop_back();
    return path;
}

std::string mesh_editor_validate_morph_snapshot_path(const std::string& raw_path) {
    if (raw_path.empty() || raw_path.find("..") != std::string::npos) {
        throw std::runtime_error("morph runtime snapshot path is invalid");
    }
    const std::size_t separator = raw_path.find_last_of("/\\");
    if (separator == std::string::npos || separator + 1 >= raw_path.size()) {
        throw std::runtime_error("morph runtime snapshot path must be an absolute app-owned temp file");
    }
    const std::string filename = raw_path.substr(separator + 1);
    const std::string prefix = "cdmw_mesh_preview_delta_";
    const std::string suffix = "_morph_runtime_snapshot.json";
    if (filename.compare(0, prefix.size(), prefix) != 0
        || filename.size() < suffix.size()
        || filename.compare(filename.size() - suffix.size(), suffix.size(), suffix) != 0) {
        throw std::runtime_error("morph runtime snapshot path is not app-owned");
    }
    const char* temp_raw = std::getenv("TEMP");
    if (temp_raw == nullptr || *temp_raw == '\0') temp_raw = std::getenv("TMPDIR");
    if (temp_raw == nullptr || *temp_raw == '\0') temp_raw = std::getenv("TMP");
    if (temp_raw == nullptr || *temp_raw == '\0') {
        throw std::runtime_error("morph runtime snapshot temp root is unavailable");
    }
    const std::string parent = raw_path.substr(0, separator);
    if (mesh_editor_snapshot_normalized_path(parent)
        != mesh_editor_snapshot_normalized_path(temp_raw)) {
        throw std::runtime_error("morph runtime snapshot path escaped the app temp root");
    }
    return raw_path;
}

std::string mesh_editor_read_morph_snapshot_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) throw std::runtime_error("cannot open morph runtime snapshot");
    const std::streamoff end = input.tellg();
    if (end <= 0 || static_cast<unsigned long long>(end) > MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_MAX_BYTES) {
        throw std::runtime_error("morph runtime snapshot size is invalid");
    }
    std::string payload(static_cast<std::size_t>(end), '\0');
    input.seekg(0, std::ios::beg);
    input.read(&payload[0], end);
    if (!input) throw std::runtime_error("cannot read complete morph runtime snapshot");
    return payload;
}

void mesh_editor_write_morph_snapshot_file(const std::string& path, const std::string& payload) {
    if (payload.empty() || payload.size() > MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_MAX_BYTES) {
        throw std::runtime_error("morph runtime snapshot size is invalid");
    }
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) throw std::runtime_error("cannot open morph runtime snapshot output");
    output.write(payload.data(), static_cast<std::streamsize>(payload.size()));
    output.flush();
    if (!output) {
        output.close();
        (void)std::remove(path.c_str());
        throw std::runtime_error("cannot write complete morph runtime snapshot");
    }
}

void mesh_editor_validate_morph_snapshot_file_identity(
    const JsonValue& request,
    const std::string& path,
    const std::string& payload
) {
    const long long declared_size = mesh_editor_snapshot_integer(request, "snapshot_byte_length", 1);
    if (static_cast<unsigned long long>(declared_size) != payload.size()) {
        throw std::runtime_error("morph runtime snapshot byte length does not match");
    }
    const std::string declared_sha256 = lower_ascii(mesh_editor_snapshot_string(request, "snapshot_sha256"));
    if (declared_sha256.size() != 64 || declared_sha256 != mesh_editor_snapshot_sha256(payload)) {
        throw std::runtime_error("morph runtime snapshot SHA-256 does not match");
    }
    (void)path;
}

void mesh_editor_validate_morph_snapshot_document(
    const JsonValue& document,
    const std::string& expected_snapshot_id
) {
    if (document.type != JsonValue::Type::Object
        || mesh_editor_snapshot_string(document, "schema") != MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA
        || mesh_editor_snapshot_integer(document, "version", 1) != 1
        || mesh_editor_snapshot_string(document, "snapshot_id") != expected_snapshot_id
        || mesh_editor_snapshot_string(document, "source_session_id").empty()) {
        throw std::runtime_error("morph runtime snapshot identity does not match");
    }
    const std::string topology_digest = lower_ascii(
        mesh_editor_snapshot_string(document, "topology_digest")
    );
    if (topology_digest.size() != 64
        || mesh_editor_snapshot_string(document, "topology_digest_algorithm") != "sha256") {
        throw std::runtime_error("morph runtime snapshot topology digest is invalid");
    }
    (void)mesh_editor_snapshot_integer(document, "retained_bytes", 1);
    (void)mesh_editor_snapshot_integer(document, "morph_state_revision");
    (void)mesh_editor_snapshot_required_member(document, "runtime", JsonValue::Type::Object);
}

std::string mesh_editor_morph_snapshot_create_session_report(
    const JsonValue& root,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    if (session.active_stroke.active
        || (session.morph && !session.morph->active_change_id.empty())) {
        throw std::runtime_error("finish or cancel the active mesh gesture before capturing Morph & Refit state");
    }
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    if (snapshot_id.empty() || snapshot_id.size() > 128) {
        throw std::runtime_error("morph runtime snapshot requires a bounded snapshot_id");
    }
    const std::string output_path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_output_path")
    );
    const std::string runtime_payload = mesh_editor_morph_runtime_snapshot_payload(session);
    const std::string topology_digest = mesh_editor_morph_topology_digest(session);
    std::ostringstream document_stream;
    document_stream << "{\"schema\":";
    write_escaped(document_stream, MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA);
    document_stream << ",\"version\":1,\"snapshot_id\":";
    write_escaped(document_stream, snapshot_id);
    document_stream << ",\"source_session_id\":";
    write_escaped(document_stream, session_id);
    document_stream << ",\"topology_digest_algorithm\":\"sha256\",\"topology_digest\":";
    write_escaped(document_stream, topology_digest);
    document_stream << ",\"retained_bytes\":" << runtime_payload.size()
        << ",\"morph_state_revision\":" << session.morph_state_revision
        << ",\"runtime\":" << runtime_payload << '}';
    const std::string document = document_stream.str();
    mesh_editor_write_morph_snapshot_file(output_path, document);
    const std::string sha256 = mesh_editor_snapshot_sha256(document);
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_create\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot\":{\"schema\":";
    write_escaped(out, MESH_EDITOR_MORPH_RUNTIME_SNAPSHOT_SCHEMA);
    out << ",\"version\":1,\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"source_session_id\":";
    write_escaped(out, session_id);
    out << ",\"path\":";
    write_escaped(out, output_path);
    out << ",\"byte_length\":" << document.size() << ",\"sha256\":";
    write_escaped(out, sha256);
    out << ",\"topology_digest\":";
    write_escaped(out, topology_digest);
    out << ",\"retained_bytes\":" << runtime_payload.size()
        << "},\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
}

std::string mesh_editor_morph_snapshot_restore_session_report(
    const JsonValue& root,
    const std::string& session_id,
    MeshEditorSession& session,
    const std::chrono::steady_clock::time_point& started
) {
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    const std::string path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_path")
    );
    const std::string payload = mesh_editor_read_morph_snapshot_file(path);
    mesh_editor_validate_morph_snapshot_file_identity(root, path, payload);
    const JsonValue document = JsonParser(payload).parse();
    mesh_editor_validate_morph_snapshot_document(document, snapshot_id);
    const std::string expected_topology = lower_ascii(
        mesh_editor_snapshot_string(document, "topology_digest")
    );
    const std::string actual_topology = mesh_editor_morph_topology_digest(session);
    if (expected_topology != actual_topology) {
        throw std::runtime_error("morph runtime snapshot topology does not match the target session");
    }
    std::shared_ptr<MeshMorphRuntime> restored = mesh_editor_morph_runtime_from_snapshot(
        mesh_editor_snapshot_required_member(document, "runtime", JsonValue::Type::Object), session
    );
    const long long snapshot_revision = mesh_editor_snapshot_integer(document, "morph_state_revision");
    session.morph_state_revision = std::max(
        session.morph_state_revision,
        std::max(snapshot_revision, restored->state_revision)
    );
    restored->state_revision = ++session.morph_state_revision;
    restored->active_change_id.clear();
    restored->active_definition_id.clear();
    restored->active_change_update_count = 0;
    session.morph = std::move(restored);
    session.active_stroke = MeshEditorStroke{};
    session.undo_stack.clear();
    session.redo_stack.clear();
    ++session.stroke_revision;
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_restore\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"topology_digest\":";
    write_escaped(out, actual_topology);
    out << ",\"retained_bytes\":" << mesh_editor_snapshot_integer(document, "retained_bytes", 1)
        << ",\"geometry_recomposed\":false,\"history_cleared\":true,\"gesture_cleared\":true,";
    mesh_editor_write_session_counts(out, session);
    out << ",\"morph_state\":";
    mesh_editor_write_morph_state(out, session);
    out << ",\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
}

std::string mesh_editor_morph_snapshot_dispose_report(
    const JsonValue& root,
    const std::string& session_id,
    const std::chrono::steady_clock::time_point& started
) {
    const std::string snapshot_id = mesh_editor_snapshot_string(root, "snapshot_id");
    const std::string path = mesh_editor_validate_morph_snapshot_path(
        mesh_editor_snapshot_string(root, "snapshot_path")
    );
    const std::string payload = mesh_editor_read_morph_snapshot_file(path);
    mesh_editor_validate_morph_snapshot_file_identity(root, path, payload);
    const JsonValue document = JsonParser(payload).parse();
    mesh_editor_validate_morph_snapshot_document(document, snapshot_id);
    if (mesh_editor_snapshot_string(document, "source_session_id") != session_id) {
        throw std::runtime_error("morph runtime snapshot dispose session does not match its owner");
    }
    if (std::remove(path.c_str()) != 0) {
        throw std::runtime_error("cannot dispose morph runtime snapshot");
    }
    const auto finished = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(finished - started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\","
           "\"protocol\":\"mesh-editor-session-json\",\"command\":\"morph_snapshot_dispose\","
           "\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"snapshot_id\":";
    write_escaped(out, snapshot_id);
    out << ",\"disposed\":true,\"metrics\":{\"cpp_ms\":" << std::setprecision(17) << cpp_ms
        << ",\"io_serialization_ms\":0}}";
    return out.str();
}

std::string mesh_editor_morph_report_json(
    const std::string& command,
    const std::string& session_id,
    const MeshEditorSession& session,
    const std::vector<SubmeshMeshEditResult>& results,
    const std::set<int>& affected,
    bool history_published,
    const std::string& delta_output_dir,
    bool include_edit_report,
    const std::chrono::steady_clock::time_point& started
) {
    const auto report_started = std::chrono::steady_clock::now();
    const double cpp_ms = std::chrono::duration<double, std::milli>(report_started - started).count();
    const std::string edit_report = include_edit_report ? mesh_edit_report_json(results, true) : std::string();
    const auto finished = std::chrono::steady_clock::now();
    const double io_ms = std::chrono::duration<double, std::milli>(finished - report_started).count();
    std::ostringstream out;
    out << "{\"status\":\"ok\",\"backend\":\"cdmw_mesh_core_0.1\",\"protocol\":\"mesh-editor-session-json\",\"command\":";
    write_escaped(out, command);
    out << ",\"session_id\":";
    write_escaped(out, session_id);
    out << ",\"affected_submesh_indices\":";
    mesh_editor_write_morph_index_set(out, affected);
    out << ",\"topology_changed\":false,\"result_count\":" << results.size()
        << ",\"history_published\":" << (history_published ? "true" : "false")
        << ",\"change_id\":";
    write_escaped(out, session.morph ? session.morph->change_id : std::string());
    out << ',';
    mesh_editor_write_session_counts(out, session);
    out << ',';
    mesh_editor_write_submesh_summaries(out, session);
    out << ',';
    mesh_editor_write_metrics(out, cpp_ms, io_ms);
    if (include_edit_report) out << ",\"edit_report\":" << edit_report;
    out << ",\"morph_state\":";
    mesh_editor_write_morph_state(out, session);
    out << '}';
    (void)delta_output_dir;
    return out.str();
}
