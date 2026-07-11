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
        return mesh_editor_open_session_report(root, session_id, native_session_id, started);
    }
    if (command == "close") {
        return mesh_editor_close_session_report(session_id, native_session_id, started);
    }

    auto found = g_mesh_editor_sessions.find(session_id);
    if (found == g_mesh_editor_sessions.end()) {
        throw std::runtime_error("missing mesh editor session");
    }
    MeshEditorSession& session = found->second;
    if (command == "summary") {
        return mesh_editor_summary_report(session_id, session, started);
    }
    if (command == "select") {
        return mesh_editor_select_session_report(root, session_id, session, started);
    }
    if (command == "undo" || command == "redo") {
        return mesh_editor_history_session_report(command, root, session_id, session, started);
    }
    if (command == "export_snapshot") {
        return mesh_editor_export_snapshot_report(root, session_id, session, started);
    }
    if (command == "apply") {
        return mesh_editor_apply_session_report(root, session_id, session, started);
    }
    throw std::runtime_error("unsupported mesh editor command: " + command);
}
