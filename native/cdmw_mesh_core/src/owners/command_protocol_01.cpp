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
