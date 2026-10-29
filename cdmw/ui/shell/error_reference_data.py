"""Generated diagnostic inventory; run scripts/generate_error_reference.py --write."""

ERROR_REFERENCE = [
  {
    "group": "archive",
    "code": "backend_incompatible",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "backend_unavailable",
    "messages": [
      "The standalone archive backend is unavailable."
    ],
    "sources": [
      "cdmw/ui/archive_browser/controller.py",
      "cdmw/ui/archive_browser/filter_workers.py",
      "cdmw/ui/archive_browser/scan_lifecycle.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "client_shutdown",
    "messages": [
      "Archive backend request stopped during application shutdown."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "dispatch_failed",
    "messages": [],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "duplicate_request",
    "messages": [
      "The request id is already active."
    ],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "file_sharing",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "invalid_archive",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "invalid_data",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "invalid_result",
    "messages": [
      "Archive backend returned an invalid result."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "invalid_stream_payload",
    "messages": [
      "Archive backend returned an invalid {kind} payload."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "item_names_unavailable",
    "messages": [],
    "sources": [
      "cdmw/services/archive_catalogue_service.py",
      "cdmw/ui/archive_browser/remote_finder_warmup.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "operation_timeout",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "permission_denied",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "process_start_failed",
    "messages": [
      "Archive backend process failed to start: {detail}"
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "protocol_failure",
    "messages": [],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py",
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "protocol_mismatch",
    "messages": [
      "Unsupported worker protocol version."
    ],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "query_recovery_failed",
    "messages": [
      "Archive query could not be retried after worker restart.",
      "Recovered query could not be dispatched.",
      "Recovered query target has an unsupported payload."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "recovery_fingerprint_changed",
    "messages": [
      "Archive sources changed while the worker was restarting; stale queries were not retried."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "recovery_open_failed",
    "messages": [
      "Archive session reopen could not be dispatched."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "recovery_session_missing",
    "messages": [
      "Archive session could not be reopened after worker restart."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "request_stalled",
    "messages": [
      "Archive operation stopped making progress for five minutes."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "source_missing",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "stale_generation",
    "messages": [
      "Archive backend request was superseded before dispatch.",
      "Archive backend response was invalidated by a newer UI generation."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "stale_response",
    "messages": [
      "Archive backend response correlation failed."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "startup_timeout",
    "messages": [
      "Archive backend did not become ready within 10 seconds."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "unknown_error",
    "messages": [],
    "sources": [
      "cdmw/services/archive_catalogue_service.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "unsupported_ignored_folders",
    "messages": [
      "The archive backend does not support custom ignored folders. Update or rebuild CDMW before scanning with these exclusions."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "unsupported_operation",
    "messages": [],
    "sources": [
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "worker_crashed",
    "messages": [
      "Archive backend stopped unexpectedly.",
      "The archive worker exited before this operation could start.",
      "Unresponsive archive worker is being stopped."
    ],
    "sources": [
      "cdmw/services/archive_catalogue_service.py",
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "worker_failure",
    "messages": [
      "Archive backend request failed."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py",
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "worker_missing",
    "messages": [],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py",
      "tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/WorkerServer.cs"
    ],
    "severity": []
  },
  {
    "group": "archive",
    "code": "write_failed",
    "messages": [
      "Archive backend request could not be written."
    ],
    "sources": [
      "cdmw/ui/shell/archive_backend_client.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "capture_blocked",
    "messages": [
      "Start/load the game, then rerun capture or pass --launch-game when launch is intended."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "client_to_screen_failed",
    "messages": [
      "Could not map game client point to screen."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "comparison_unavailable",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "capture",
    "code": "focus_failed",
    "messages": [
      "Game window did not have focus after prompt interaction.",
      "Game window did not have focus; skipped key {key_label}.",
      "Game window did not have focus; skipped window capture.",
      "Game window did not have focus; skipped {button_key} mouse click."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "game_exe_missing",
    "messages": [
      "Crimson Desert executable is missing: {exe}"
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "game_launch_failed",
    "messages": [
      "Could not launch Crimson Desert: {exc}"
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "game_launch_requested",
    "messages": [
      "Launched Crimson Desert process."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "game_window_not_found",
    "messages": [
      "No running Crimson Desert game window was found."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_masked_detail_contrast",
    "messages": [
      "Preview has weaker masked detail contrast than the reference; increase masked detail contrast before brightness hacks."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_masked_gold_strength",
    "messages": [
      "Reference contains gold that preview under-represents; raise masked gold strength or mask contrast."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_masked_green_strength",
    "messages": [
      "Reference contains green that preview under-represents; raise masked green strength or mask visibility."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_masked_silver_strength",
    "messages": [
      "Reference contains silver that preview under-represents; raise masked silver strength or neutral metal base visibility."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_preview_luma_or_source_brightness",
    "messages": [
      "Preview is darker than the reference; raise source brightness slightly or lift the neutral metal base/tone response."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_red_gem_or_emissive_strength",
    "messages": [
      "Reference contains red that preview under-represents; check gem base/emissive color and red channel handling."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "increase_tint_or_mask_saturation",
    "messages": [
      "Preview is less saturated than the reference; increase tint strength or masked green/gold/silver layer visibility."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "key_send_failed",
    "messages": [
      "Could not send key {key_label} to game window."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "key_sent",
    "messages": [
      "Sent key {key_label} to game window."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "lower_roughness_or_raise_reflection",
    "messages": [
      "Preview lacks highlights; lower roughness or raise specular/environment reflection."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "missing_masked_details",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "mouse_click_sent",
    "messages": [
      "Sent {button_key} mouse click to game window."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "mouse_move_failed",
    "messages": [
      "Could not move cursor inside game window."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "raise_roughness_or_reduce_reflection",
    "messages": [
      "Preview has too many highlights; raise roughness or reduce specular/environment reflection."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "reduce_blue_gem_or_check_channel_swizzle",
    "messages": [
      "Preview has more blue than the reference; check gem base/emissive color and possible red/blue channel swizzle."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "reduce_preview_luma_or_source_brightness",
    "messages": [
      "Preview is brighter than the reference; lower source brightness or compress the metal base tone response."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "reduce_tint_or_mask_saturation",
    "messages": [
      "Preview is more saturated than the reference; reduce tint strength or masked layer saturation."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "source_missing",
    "messages": [
      "Source mod directory is missing: {source}"
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_bright",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_dark",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_dull",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_glossy",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_matte",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "too_saturated",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "unexpected_blue",
    "messages": [],
    "sources": [
      "cdmw/rendering/preview_comparison.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "unexpected_mod_name",
    "messages": [
      "Refusing to sync anything except TestRunSword."
    ],
    "sources": [
      "cdmw/rendering/test_run_sword_tuning.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "unsupported_mouse_button",
    "messages": [
      "Unsupported mouse button: {button}"
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "unsupported_platform",
    "messages": [
      "In-game window capture is only available on Windows.",
      "Key send is only available on Windows.",
      "Mouse input is only available on Windows.",
      "Window capture is only available on Windows.",
      "Window interaction is only available on Windows."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "window_capture_failed",
    "messages": [
      "Could not capture game window: {exc}"
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "window_captured",
    "messages": [
      "Captured game client area."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "window_interacted_for_keyboard_prompts",
    "messages": [
      "Focused game window and clicked inside client area."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "window_rect_empty",
    "messages": [
      "Game client bounds were empty."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "capture",
    "code": "window_rect_failed",
    "messages": [
      "Could not read game client bounds."
    ],
    "sources": [
      "cdmw/rendering/ingame_capture.py"
    ],
    "severity": []
  },
  {
    "group": "dds",
    "code": "bad_dimensions",
    "messages": [
      "DDS dimensions are invalid: {width}x{height}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "bad_header_size",
    "messages": [
      "DDS header size is {header_size}, expected 124."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "bad_magic",
    "messages": [
      "DDS magic is missing."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "bad_pixel_format_size",
    "messages": [
      "DDS pixel format size is {pf_size}, expected 32."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "depth_zero",
    "messages": [
      "DDS depth field is 0; preserve the target template/PATHC context for Crimson replacements."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "dx10_header_too_short",
    "messages": [
      "DDS declares a DX10 header, but the 20-byte DX10 payload is missing."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "effective_last4",
    "messages": [
      "Effective Crimson last4 class is 0x{effective_last4}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "dds",
    "code": "header_too_short",
    "messages": [
      "DDS header is too short: {len(blob)} bytes."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "last4_mismatch",
    "messages": [
      "DDS header last4 is 0x{crimson_last4_header}; expected 0x{effective_last4} for this path/format."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "mip_count_zero",
    "messages": [
      "DDS mip count field is 0; treating it as 1."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "missing_mips",
    "messages": [
      "DDS mip chain has {mip_count} level(s); {expected_mips} would be a full chain for {width}x{height}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "non_power_of_two_dims",
    "messages": [
      "DDS dimensions are not powers of two: {width}x{height}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "overlay_patched",
    "messages": [
      "DDS header last4 already matches 0x{effective_last4}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "dds",
    "code": "payload_size_valid",
    "messages": [],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "dds",
    "code": "payload_truncated",
    "messages": [],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "dds",
    "code": "requires_pathc",
    "messages": [
      "DDS format {dds_format or dxgi_format} uses DX10 metadata and should be registered through PATHC/manifest metadata."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_alpha_layout",
    "messages": [
      "DDS uses an unsupported alpha-only layout: bits={rgb_bit_count}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_dxgi_format",
    "messages": [
      "DDS uses an unknown DXGI format id: {dxgi_format}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_fourcc",
    "messages": [
      "DDS uses an unknown legacy FOURCC: {pretty_fourcc}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_luminance_layout",
    "messages": [
      "DDS uses an unsupported luminance layout: bits={rgb_bit_count}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_pixel_format_flags",
    "messages": [
      "DDS uses unsupported pixel format flags: 0x{pf_flags}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "dds",
    "code": "unknown_rgb_layout",
    "messages": [
      "DDS uses an unsupported RGB layout: bits={rgb_bit_count}."
    ],
    "sources": [
      "cdmw/core/texture_pipeline/inspection.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "independent",
    "code": ":bindings",
    "messages": [
      "Retained provider bindings have not changed."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":environment",
    "messages": [
      "Executable, recorded runtime files, compiler and physical underlay remain the same."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":other-packages",
    "messages": [
      "Other selected package content and bindings remain the same."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":provider",
    "messages": [
      "Provider presence follows the intended experiment stage."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":restored-context",
    "messages": [
      "Restored package content, bindings, source contracts and prepared output match the baseline."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":same-absent-context",
    "messages": [
      "The prepared absent-provider context stayed the same."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": ":selected-files",
    "messages": [
      "Every explicitly selected save file exists in this copy."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "absent-load-input",
    "messages": [
      "The absent-provider load starts with the original selected save bytes."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "absent-load-no-save",
    "messages": [
      "The selected save bytes did not change during the reported load-only case."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "baseline-provider",
    "messages": [
      "The baseline selects the provider virtually."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "borrowed-contribution-resources",
    "messages": [
      "Decoded contribution references still reach borrowed source resources."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "changed-proposed-context",
    "messages": [],
    "sources": [
      "cdmw/domain/virtual_session_receipt.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "existing-content-edits",
    "messages": [
      "The package intentionally owns assignments to existing game content."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "new-absent-save",
    "messages": [
      "The reported absent-provider save has different selected bytes; this alone does not prove a game write."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "no-new-item",
    "messages": [
      "The package does not define a new inventory item."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "package-dependency",
    "messages": [
      "The contribution depends on other packages with exact installation pins."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "restore-new-save-input",
    "messages": [
      "The restored-provider load starts with the newly written copy, not the original recovery save."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "restore-save-attempt-input",
    "messages": [
      "The restored-provider case retains the attempted-save bytes. A failed or unknown attempt does not establish a committed save."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "restored-load-no-save",
    "messages": [
      "The selected save bytes stayed unchanged during the restored-provider load-only case. Different bytes, including possible autosaves, leave this sequence inconsistent and unverified."
    ],
    "sources": [
      "cdmw/domain/virtual_save_evidence.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "shared-file-composition",
    "messages": [
      "This backend composes shared game files. Native independent registration and resource discovery are not proven."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "shared-integration",
    "messages": [
      "Acquisition changes add membership to existing shop or item-group records."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "unknown-proposed-context",
    "messages": [],
    "sources": [
      "cdmw/domain/virtual_session_receipt.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "unverified-resource-assessment",
    "messages": [
      "No final resource ownership assessment was captured."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "independent",
    "code": "unverified-resource-boundaries",
    "messages": [
      "The resource graph lists unverified boundaries or a partial edge inventory."
    ],
    "sources": [
      "cdmw/services/independent_item_isolation.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "base_texture_used_as_emissive",
    "messages": [
      "Same DDS is bound to both base/color and emissive parameters; source emissive authority is ambiguous."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "compiler_failed",
    "messages": [
      "{type(exc).__name__}: {exc}"
    ],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "compiler_fallback",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "compiler_manifest_invalid",
    "messages": [
      "canonical material compiler exceeded the generated-channel limit",
      "canonical material compiler returned an invalid generated-channel list",
      "canonical material compiler returned an invalid submesh list",
      "canonical material compiler returned an invalid submesh row",
      "canonical material compiler returned invalid channel metadata"
    ],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "compiler_owner_conservation_failed",
    "messages": [
      "generated PAC channels were rejected because their exact material owner was not conserved"
    ],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "generated_base_luminance_capped",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "generated_channel_encode_failed",
    "messages": [
      "{encode_channel}: {type(exc).__name__}: {exc}"
    ],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "generated_channel_missing",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "generated_channel_outside_owned_root",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "inspection_failed",
    "messages": [],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "materials",
    "code": "material_synthesis_fallback",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_rust_authoring.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "missing_payload",
    "messages": [
      "DDS payload bytes and source file are unavailable."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "materials",
    "code": "multi_role_texture_binding",
    "messages": [
      "DDS has multiple material binding roles; verify routing is intentional."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "neutral_metal_base_synthesized",
    "messages": [
      "weapon/armor metal had no reliable full base albedo; neutral base seeded from vertex/material/category hints"
    ],
    "sources": [
      "cdmw/rendering/native_preview_material_contract.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "no_reliable_full_base_albedo",
    "messages": [
      "Crimson texturelayer diffuse inputs were retained as masked layer contribution, not whole-surface albedo"
    ],
    "sources": [
      "cdmw/rendering/native_preview_material_contract.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "normal_format_not_bc5",
    "messages": [
      "Normal texture is not BC5; verify tangent-space XY packing and normal Y policy."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "normal_srgb_format",
    "messages": [
      "Normal texture uses an sRGB format; normals should be linear."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "normal_y_policy",
    "messages": [
      "Normal Y policy is recorded for preview/export review."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "normal_y_policy_unconfirmed",
    "messages": [
      "Normal source filename did not declare green_up/directx; verify Y was not flipped incorrectly."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "source_alpha_from_texture_channel",
    "messages": [],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_alpha_intent_without_opacity_evidence",
    "messages": [
      "Material name/class implies glass or translucent response, but no alpha/opacity source channel was found."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_alpha_without_opacity_texture",
    "messages": [
      "Source material declares alpha but no opacity/alpha texture slot is present."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "source_base_texture_bound_as_emissive",
    "messages": [
      "Texture name/path looks like a base color texture but is routed through an emissive slot."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "source_base_texture_bound_as_normal",
    "messages": [
      "Texture name/path looks like a base color texture but is routed through a normal slot."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "source_emissive_scalar_no_texture",
    "messages": [
      "Source material has emissive scalar/color data but no emissive texture."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_legacy_fixed_function_workflow",
    "messages": [
      "Source material uses legacy fixed-function/scalar channels rather than glTF PBR workflow."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_material_response_texture_bound_as_base",
    "messages": [
      "Texture name/path looks like packed material response data but is routed through a base color slot."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "source_missing_base_color",
    "messages": [
      "Source material has no base-color texture in the package preview model."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "source_missing_emissive",
    "messages": [
      "Source material has no emissive texture or scalar hint."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_missing_metalness",
    "messages": [
      "Source material has no metalness texture or scalar hint; preview/export must use defaults or target response."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_missing_roughness",
    "messages": [
      "Source material has no roughness texture or scalar hint; preview/export must use defaults or target response."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_missing_roughness_metalness",
    "messages": [],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_missing_{channel}",
    "messages": [],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_packed_a_channel_technical",
    "messages": [],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_spec_gloss_derived_material_channels",
    "messages": [
      "Specular/glossiness source channels will derive roughness/metalness for Crimson material masks."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_spec_gloss_texture_as_base_color",
    "messages": [
      "Specular/gloss texture appears to be used as base color; verify source workflow routing."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "source_spec_gloss_texture_bound_as_base",
    "messages": [
      "Texture name/path looks like specular-glossiness data but is routed through a base color slot."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "source_vertex_alpha_opacity",
    "messages": [
      "Source material has vertex alpha opacity data."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "source_vertex_color_present",
    "messages": [
      "Source material has vertex color data that can tint or replace base color."
    ],
    "sources": [
      "cdmw/core/external_model_audit.py",
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "technical_slot_srgb_format",
    "messages": [
      "Technical/material slot uses sRGB format; packed scalar channels should be linear."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "texture_bound_to_visible_and_technical_roles",
    "messages": [
      "Same DDS is bound to visible color/emissive and technical material roles."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "materials",
    "code": "texturelayer_kept_masked",
    "messages": [],
    "sources": [
      "cdmw/rendering/native_preview_material_contract.py"
    ],
    "severity": []
  },
  {
    "group": "materials",
    "code": "uncompressed_channel_order",
    "messages": [
      "Uncompressed DDS channel order detected: {channel_order.upper()}. Verify RGBA/BGRA expectations."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "visible_color_linear_format_review",
    "messages": [
      "Visible color DDS is not marked sRGB; verify intended color space."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "materials",
    "code": "visible_color_technical_format",
    "messages": [
      "Visible color slot uses a scalar/vector technical DDS format."
    ],
    "sources": [
      "cdmw/core/final_package_material_authority.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_runtime",
    "code": "EDIT_FINISH_PENDING_COMMANDS",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "EDIT_REQUEST_STALE",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "EDIT_SELECTION_GENERATION_MISMATCH",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "EDIT_SESSION_RECOVERY_REQUIRED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_COMPILE_FAILED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_IMPORT_MANIFEST_MISSING",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_NO_TEXTURE_RESOURCES",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_PUBLICATION_SEND_FAILED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_PUBLICATION_STALE",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_REQUIRED_TEXTURE_MISSING",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_ROLE_ACK_TIMEOUT",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "MAT_ROLE_UPDATE_REJECTED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "PACKAGE_ATOMIC_COMMIT_FAILED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "PACKAGE_RESOURCE_REFERENCE_MISSING",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "RENDERER_GENERATION_RETIRED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "RENDERER_PROCESS_UNAVAILABLE",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "VIEW_MODE_SEND_FAILED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "VIEW_MODE_STALE_UPDATE",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "WRITEBACK_EXACT_WRITER_REQUIRED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "WRITEBACK_OUTPUT_SIGNATURE_MISMATCH",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "WRITEBACK_PROVENANCE_MISSING",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_runtime",
    "code": "WRITEBACK_TOPOLOGY_UNSUPPORTED",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_editor_error_codes.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "BONE_DATA_CHANGED",
    "messages": [
      "A direct topology vertex did not preserve its original bone indices or weights.",
      "Bone indices or weights changed.",
      "Topology output does not carry one skin row per output vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "EMPTY_MESH_ASSET",
    "messages": [
      "MeshAsset has no LODs."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "FALLBACK_SCAN_REBUILD_BLOCKED",
    "messages": [
      "Fallback-scan mesh layouts are preview-only until explicitly overridden."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "INVALID_INDEX_RANGE",
    "messages": [
      "Index buffer references a missing vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "INVALID_VERTEX_POSITION",
    "messages": [
      "Vertex position is NaN, infinite, or malformed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "LOD_COUNT_CHANGED",
    "messages": [
      "LOD count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "MATERIAL_SLOT_COUNT_CHANGED",
    "messages": [
      "Material slot count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "NORMAL_DATA_MISSING",
    "messages": [
      "Original normals are not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "RAW_VERTEX_RECORDS_CHANGED",
    "messages": [
      "A derived topology vertex must not carry a synthesized raw record.",
      "A direct topology vertex did not preserve its original raw record.",
      "Original raw vertex records were not preserved.",
      "Topology output does not carry one raw vertex record entry per output vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SOURCE_INDEX_COUNT_CHANGED",
    "messages": [
      "A topology-changed submesh must retain the original source index count.",
      "Submesh source index count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error",
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SOURCE_INDEX_MAP_MISSING",
    "messages": [
      "A topology-changed submesh must leave the same-count source index map empty.",
      "Each edited index must map back to an original source index."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SOURCE_VERTEX_MAP_MISSING",
    "messages": [
      "Each edited vertex must map back to an original source vertex.",
      "Topology source vertex map does not match the validated vertex origins."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SOURCE_VERTEX_OFFSET_CHANGED",
    "messages": [
      "A derived topology vertex must report no original record offset.",
      "A direct topology vertex did not preserve its original record offset."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SUBMESH_COUNT_CHANGED",
    "messages": [
      "Submesh count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SUBMESH_INDEX_COUNT_CHANGED",
    "messages": [
      "Submesh index count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "SUBMESH_VERTEX_COUNT_CHANGED",
    "messages": [
      "Submesh vertex count changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "TANGENT_DATA_MISSING",
    "messages": [
      "Original tangent data is not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "UNKNOWN_FIELDS_CHANGED",
    "messages": [
      "Unknown submesh fields were not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "UNKNOWN_SECTIONS_CHANGED",
    "messages": [
      "Unknown binary sections were not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "UV_DATA_MISSING",
    "messages": [
      "Original UV channel is not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "VERTEX_STRIDE_CHANGED",
    "messages": [
      "Original vertex stride changed."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py"
    ],
    "severity": [
      "error"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "blocked_edit_operation",
    "messages": [
      "Edit operation is blocked by default: {name}."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "bone_weight_row_mismatch",
    "messages": [
      "Bone index and weight row lengths differ."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "bounds_mismatch",
    "messages": [
      "Geometry extends outside stored mesh bounds; update bounds before export."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "degenerate_face",
    "messages": [
      "Face uses the same vertex more than once."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "disallowed_edit_operation",
    "messages": [
      "Edit operation is not allowed by sidecar rules: {name}."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "duplicate_face",
    "messages": [
      "Duplicate triangle found."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "empty_mesh",
    "messages": [
      "Mesh has no parts to export."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "empty_part",
    "messages": [
      "Mesh part has no vertices."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "hair_output",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_service_rebuild.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "inferred_parse_confidence",
    "messages": [
      "Parser confidence is inferred; verify the no-op round-trip before final rebuild."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_bone_index",
    "messages": [
      "Vertex references an invalid or missing bone."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_bone_weight",
    "messages": [
      "Vertex has an invalid bone weight."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_face",
    "messages": [
      "Face is not a valid triangle."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_face_index",
    "messages": [
      "Face references a missing vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_operation_submesh",
    "messages": [
      "Edit operation targets a missing submesh."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_safe_skin_weight_row",
    "messages": [
      "Safe PAC skin-weight rows must contain one to six unique slots from the original palette and finite, nonnegative normalized weights."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "invalid_vertex_position",
    "messages": [
      "Vertex position is missing or non-finite."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "large_scale_bounds",
    "messages": [
      "Mesh bounds are very large; verify scale before export."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "lod_count_changed",
    "messages": [
      "LOD count changed; LOD replacement is blocked by default."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "lod_identity_changed",
    "messages": [
      "LOD identity metadata was not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "lod_submesh_count_changed",
    "messages": [
      "LOD submesh count changed; topology replacement is blocked by default."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "material_slot_changed",
    "messages": [
      "Material slot changes are blocked by default; preserve the original material unless an explicit safe material operation exists."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "material_slot_count_changed",
    "messages": [
      "Material slot count changed; material replacement is blocked by default."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "material_slot_count_mismatch",
    "messages": [
      "Edited part count differs from original material slot count."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing-sidecars",
    "messages": [
      "Material sidecars were not resolved. Import can continue, but texture bindings may be incomplete."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "missing-uvs",
    "messages": [
      "Missing UVs can make textures invisible or incorrect in-game."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "missing_edit_operation",
    "messages": [
      "Edit operation is missing."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_edit_operations",
    "messages": [
      "Imported OBJ sidecar rebuild requires explicit Mesh Editor v2 edit operations."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_material_slot",
    "messages": [
      "Mesh part has no material slot."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_normals",
    "messages": [
      "Normal count does not match vertex count."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_referenced_texture",
    "messages": [
      "Referenced texture is not available: {texture}."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_skeleton_metadata",
    "messages": [
      "Skinned mesh export needs linked skeleton metadata before export.{detail}"
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_tangents",
    "messages": [
      "Tangents/bitangents are missing; generate them before final export if the target shader needs them."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "missing_texture_reference",
    "messages": [
      "Mesh part has no referenced texture."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "no_op_roundtrip_not_passed",
    "messages": [
      "No-op round-trip status is {status}; rebuild is blocked."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "no_op_roundtrip_tolerant_differences",
    "messages": [
      "No-op round-trip passed with documented non-identical bytes."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "no_op_roundtrip_unexpected_differences",
    "messages": [
      "No-op round-trip has unexpected byte differences."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "operation_source_map_invalid",
    "messages": [
      "Same-count edit operation source vertex map contains invalid entries.",
      "Topology edit operation source vertex map contains invalid entries."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "operation_source_map_missing",
    "messages": [
      "Safe edit operation requires a source vertex map for every edited vertex.",
      "Topology edit operation requires one source vertex map entry per output vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "operation_vertex_count_mismatch",
    "messages": [
      "Edit operation expected {operation.vertex_count} vertices but {target_description}.",
      "Topology edit operation expected {operation.vertex_count} vertices but submesh has {actual}."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "original-sidecar-baseline-missing",
    "messages": [
      "The tool could not recover the original archive sidecar bindings for one or more selected targets, so binding-level compatibility checks are incomplete."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "paired-pamlod-restored",
    "messages": [
      "Paired PAMLOD rebuild is prepared for {paired_lod_path}."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "part_has_no_faces",
    "messages": [
      "Mesh part has no faces and will not render."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "preserved_unnormalized_bone_weights",
    "messages": [
      "Bone weights are not normalized, but they match the original asset and will be preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "replacement_mapping",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_replacement_output.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "replacement_writer",
    "messages": [],
    "sources": [
      "cdmw/services/mesh_service_rebuild.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "selected-sidecar-no-bindings",
    "messages": [
      "The selected material sidecar file(s) were loaded, but no supported material/texture bindings were detected. Import can continue, but compatibility checks are limited."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar-binding-targets-changed",
    "messages": [
      "{len(changed)} sidecar binding locator(s) now point to different texture target(s). This can change how the model shades or make parts render incorrectly."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar-bindings-added",
    "messages": [
      "{len(added)} extra sidecar binding locator(s) were added compared with the original archive sidecar. This is allowed, but it should be reviewed if the model is expected to remain game-compatible."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar-bindings-missing",
    "messages": [
      "{len(missing)} original sidecar binding locator(s) are missing from the selected local sidecar set. Missing bindings can leave textures, masks, or support maps unassigned."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar_material_name_changed",
    "messages": [
      "OBJ sidecar material changed for submesh {submesh_index}: expected {expected_material}, got {actual_material}."
    ],
    "sources": [
      "cdmw/modding/mesh_obj_importer.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar_texture_path_changed",
    "messages": [
      "OBJ sidecar texture changed for submesh {submesh_index}: expected {expected_texture}, got {actual_texture}."
    ],
    "sources": [
      "cdmw/modding/mesh_obj_importer.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "sidecar_warning",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_layout_unproven",
    "messages": [
      "Safe skin-weight replacement requires the proven 40-byte pac_slot_u10x6 layout."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_palette_changed",
    "messages": [
      "Safe PAC skin-weight replacement requires the original submesh palette metadata."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_protected_influences_present",
    "messages": [
      "This PAC uses protected extra influence lanes, so its skin weights cannot be edited safely."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_source_map_changed",
    "messages": [
      "Safe PAC skin-weight replacement requires the original one-to-one LOD 0 source map."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_source_offsets_changed",
    "messages": [
      "Safe PAC skin-weight replacement requires every original vertex-record offset."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skin_weight_topology_changed",
    "messages": [
      "Safe PAC skin-weight replacement requires unchanged vertex and face topology."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "skinning_count_mismatch",
    "messages": [
      "An explicit skin-weight edit must retain complete bone index/weight rows.",
      "Bone index/weight rows must match vertex count."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "source_index_count_changed",
    "messages": [
      "Source index count was not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "source_vertex_map_invalid",
    "messages": [
      "Changed geometry source vertex map contains invalid entries.",
      "Changed geometry source vertex map disagrees with the validated topology origins."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "source_vertex_map_missing",
    "messages": [
      "Changed geometry requires a source vertex map for every edited vertex."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "source_vertex_offsets_changed",
    "messages": [
      "Source vertex offsets were not preserved.",
      "Topology source vertex offsets disagree with the validated vertex origins."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "submesh-count-drift",
    "messages": [],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "submesh_index_count_changed",
    "messages": [
      "Submesh index count changed; topology replacement is blocked by default."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "submesh_vertex_count_changed",
    "messages": [
      "Submesh vertex count changed; topology replacement is blocked by default."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "supplemental-targets-restored",
    "messages": [
      "Recovered {len(mapped)} selected supplemental target path(s)."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "tangent_count_mismatch",
    "messages": [
      "Tangent count does not match vertex count."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "texture_reference_changed",
    "messages": [
      "Texture reference changes are blocked by default; preserve the original texture unless an explicit safe material operation exists."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "too_many_bone_influences",
    "messages": [
      "Vertex has more than {influence_limit} bone influences."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "topology_operation_contract_unsupported",
    "messages": [
      "Topology edit operation names an unsupported provenance contract."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "topology_operation_metadata_missing",
    "messages": [
      "Topology edit operation is missing metadata: {', '.join(missing)}."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "topology_operation_provenance_missing",
    "messages": [
      "Topology edit operation requires validated topology provenance on its submesh."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unknown_fields_changed",
    "messages": [
      "Unknown submesh fields were not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unknown_parse_confidence",
    "messages": [
      "Parser confidence is unknown: {confidence}."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unknown_sections_changed",
    "messages": [
      "Unknown binary sections were not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unmapped-sidecar-targets",
    "messages": [
      "{len(unmapped)} selected sidecar file(s) could not be mapped back to archive targets. Examples: {_summarize_import_values(names)}."
    ],
    "sources": [
      "cdmw/core/archive_mesh_import_validation.py"
    ],
    "severity": []
  },
  {
    "group": "mesh_validation",
    "code": "unnormalized_bone_weights",
    "messages": [
      "Vertex bone weights are not normalized."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unsafe_parse_confidence",
    "messages": [
      "Parser confidence is {confidence}; rebuild is blocked until the layout is exact or inferred."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unsupported_edit_operation",
    "messages": [
      "Edit operation is not supported for safe rebuild: {name}."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unsupported_mesh_format",
    "messages": [
      "Unsupported game mesh format for export: {mesh_format or 'unknown'}."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unsupported_operation_lod",
    "messages": [
      "Only LOD 0 edit operations are supported by the current rebuild path."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "unsupported_{mesh_format}_topology_change",
    "messages": [
      "{mesh_format.upper()} export cannot use this topology change safely yet."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "untracked_edit_channel",
    "messages": [
      "Mesh channel changed without a matching safe edit operation: {channel}.",
      "Mesh submesh count changed without a matching safe edit operation."
    ],
    "sources": [
      "cdmw/domain/mesh/operations.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "uv_count_mismatch",
    "messages": [
      "UV count does not match vertex count."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "vertex_stride_changed",
    "messages": [
      "Original vertex stride was not preserved."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "zero_scale_bounds",
    "messages": [
      "Mesh bounds are effectively zero-sized."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "mesh_validation",
    "code": "{code}_blocks_rebuild",
    "messages": [
      "{message} Rebuild is blocked until the sidecar metadata is restored or an explicit safe material operation exists."
    ],
    "sources": [
      "cdmw/domain/mesh/export_validation.py"
    ],
    "severity": [
      "blocker"
    ]
  },
  {
    "group": "new_item",
    "code": "authoring.invalid",
    "messages": [],
    "sources": [
      "cdmw/ui/new_item/controller.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "body_visibility.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "bonuses.levels",
    "messages": [
      "Choose each enhancement level at most once."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "bonuses.range",
    "messages": [
      "Bonuses require a valid BuffInfo key and signed parameter level."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "buy_price.duplicate",
    "messages": [
      "Level {edit.level} prices item {edit.item_key} twice."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "buy_price.level",
    "messages": [
      "Enchant level {edit.level} is negative."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "buy_price.not_in_template",
    "messages": [
      "Level {edit.level} of {template.internal_name} has no buy price in item {edit.item_key}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "buy_price.range",
    "messages": [
      "Prices are unsigned 32-bit; {edit.price} is not."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "desc_key.needed",
    "messages": [
      "The template has a description; the clone needs a description key too (leave both keys unset to allocate them together)."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "desc_key.same_as_name",
    "messages": [
      "The description key must differ from the name key."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.emitters.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.layer.invalid",
    "messages": [
      "Invalid layer name or visibility."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.layers.limit",
    "messages": [
      "An item supports at most 16 effect layers."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.look.color",
    "messages": [
      "The effect look's colour is three components between 0 and 1."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.look.unproven",
    "messages": [
      "A look edits the cloned effect's named colours, brightness, particle scale, spawn counts and lifetimes in place; which of them the game honours is unproven until the first in-game look."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "effect.look.{name}",
    "messages": [
      "The effect look's {name} is a factor between 0.05 and 20 (1 = as shipped)."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.offset",
    "messages": [
      "The effect position is three metre-scale numbers within 5 of the item's origin."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.rotation",
    "messages": [
      "The effect rotation is three Euler degrees about the item's axes (x, then y, then z), each within 180."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.scale",
    "messages": [
      "The effect scale is a factor between 0.01 and 10."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.shape",
    "messages": [
      "An effect is named `<stem>.<kind>.effect`, with a shipped level, action, gimmick, system or sequencer reference."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.unknown",
    "messages": [
      "No shipped effect is named {stem}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "effect.unproven",
    "messages": [
      "The visual effect is grafted into every compatible prefab the item owns as an EffectComponent. Compatibility is checked structurally; verify the final placement and fit in game."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "enhancement.own_unproven",
    "messages": [
      "Cloned enhancement rows are unproven in game; sharing the template's rows is the verified form."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "enhancement.shared",
    "messages": [
      "The item enhances through the template's own transition rows, which name the template."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "new_item",
    "code": "glow.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "icon.generated_for_template_model",
    "messages": [
      "A generated icon on the template's model will look like the template's icon; that is allowed, but check it is what you want."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "info"
    ]
  },
  {
    "group": "new_item",
    "code": "internal_name.empty",
    "messages": [
      "Give the item an internal name."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "internal_name.same_as_template",
    "messages": [
      "The clone needs its own internal name."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "internal_name.shape",
    "messages": [
      "Internal names are ASCII letters, digits and underscores, starting with a letter, at most 64 characters."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "internal_name.taken",
    "messages": [
      "An item named {name} already exists."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_behavior.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_definition.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_groups.ignored",
    "messages": [
      "The listed item groups are ignored while the template's groups are selected."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "item_groups.unknown",
    "messages": [
      "Unknown item group key(s): {', '.join((str(k) for k in unknown))}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_inventory.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_key.range",
    "messages": [
      "Item keys are positive 32-bit integers."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_key.taken",
    "messages": [
      "Item key {spec.item_key} is already used."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_property.range",
    "messages": [
      "{name} must be an integer in 0..{maximum}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_settings.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_settings.use_model",
    "messages": [
      "Inventory-use templates keep their source appearance; equipment model and effect authoring require an equipment template."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "item_stats.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "max_stack.range",
    "messages": [
      "Max stack count is a positive 32-bit integer."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "model_placement_not_applied",
    "messages": [
      "{self.model_import.label} is imported but its placement is not applied yet: step 3, Apply the placement."
    ],
    "sources": [
      "cdmw/ui/new_item/controller.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "names.empty",
    "messages": [
      "The {code} display name is empty; leave the language out to fall back to English."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "names.english_missing",
    "messages": [
      "An English display name is required; other languages default to it."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "names.language_unknown",
    "messages": [
      "{code} is not one of the shipped language tables."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.insert_unsupported",
    "messages": [
      "Adding a stock entry is not available in this build; swap an existing entry instead."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.none",
    "messages": [
      "No shop placement: the item will exist but nothing in the game hands it out."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "placement.old_item_missing",
    "messages": [
      "Choose which stock entry the new item replaces."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.old_item_not_in_store",
    "messages": [
      "{store} does not stock {placement.old_item_name}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.price",
    "messages": [
      "A placement price is a non-negative 32-bit integer."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.price_ignored",
    "messages": [
      "StoreInfo entries carry no price of their own; the shop prices the item from its buy-price list, so this price is not written."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "placement.price_missing",
    "messages": [
      "No shop price is set. Add one before placing the item in a shop."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "placement.stock_count",
    "messages": [
      "A stock count is 1 or more (0xFFFFFFFF for unlimited)."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.store_missing",
    "messages": [
      "Choose a store."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "placement.store_unknown",
    "messages": [
      "There is no store named {store}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "price.duplicate",
    "messages": [
      "Item {edit.item_key} is priced twice."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "price.not_in_template",
    "messages": [
      "{template.internal_name} has no price in item {edit.item_key}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "price.range",
    "messages": [
      "Prices are unsigned 32-bit; {edit.price} is not."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "recipes.inputs",
    "messages": [
      "Recipe inputs need a supported item or group and a positive quantity."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "recipes.keys",
    "messages": [
      "Choose each valid source recipe once."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "recipes.outputs",
    "messages": [
      "Recipe outputs require valid quantities and enhancement levels."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "rewards.route",
    "messages": [
      "Choose a supported reward consumer, entry and quantity range."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "shader_controls.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "slots.capacity",
    "messages": [
      "The selected perks need more slots. Increase capacity or explicitly remove perks."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py",
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "slots.experimental",
    "messages": [
      "More than five slots is experimental."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "slots.no_stat_block",
    "messages": [
      "The template's socket boundary has not been decoded."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "slots.range",
    "messages": [
      "Each slot needs an item key and positive unlock amount; values must fit u32."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "slots.too_many",
    "messages": [
      "At most eight socket slots fit the supported row."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "slots.unknown_material",
    "messages": [
      "A socket unlock material is missing from the active item table."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "sockets.no_stat_block",
    "messages": [
      "{template.internal_name}'s stat block did not decode, so its socket items cannot be replaced."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "sockets.not_gear",
    "messages": [
      "Not Abyss Gear socket items (nothing shipped embeds them): {', '.join((str(k) for k in odd))}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "sockets.range",
    "messages": [
      "Socket items are positive 32-bit item keys."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "sockets.too_many",
    "messages": [
      "At most {MAX_SOCKET_ITEMS} socket items fit the row."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "sockets.unknown_item",
    "messages": [
      "Not item keys: {', '.join((str(k) for k in unknown))}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "sockets.unproven",
    "messages": [
      "No shipped item carries more than {MAX_SHIPPED_SOCKET_ITEMS} socket items; more is unproven in game."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "stat.duplicate",
    "messages": [
      "Level {edit.level} sets stat {edit.status_key} twice."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stat.level",
    "messages": [
      "Enchant level {edit.level} is negative."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stat.not_in_template",
    "messages": [
      "Level {edit.level} of {template.internal_name} has no {edit.status_key} entry; adding stats needs the stat-block rebuild, which this build does not have."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stat.range",
    "messages": [
      "Stat values are signed 32-bit; {edit.value} is not."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stat.unknown_status",
    "messages": [
      "{edit.status_key} is not a StatusInfo key."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stem.same_as_template",
    "messages": [
      "The new model family needs its own stem."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stem.shape",
    "messages": [
      "Model stems are lowercase letters, digits and underscores, at most 64 characters, no path separators."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stem.taken",
    "messages": [
      "Stem {stem} cannot be used: {reason}."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "stem.unused",
    "messages": [
      "A stem was given but the item keeps the template's model and icon, so it is not used."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "surface_settings.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.mismatch",
    "messages": [
      "The snapshot describes a different template than the spec names."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.missing",
    "messages": [
      "Choose a template item."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.no_owned_stems",
    "messages": [
      "{template.internal_name} owns no prefab stems to clone (all of its parts are borrowed)."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.no_stat_block",
    "messages": [
      "{template.internal_name}'s stat block did not decode; stats and prices cannot be edited on this template."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "new_item",
    "code": "template.not_equipment",
    "messages": [
      "{template.internal_name} has no equip type; only equipment can be cloned into a new item."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.placement",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "template.unknown",
    "messages": [
      "Item {template.key} is not in the table."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "translucency.invalid",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant.dye",
    "messages": [
      "Dye assignments need exact names and three supported slot indices."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant.glow",
    "messages": [
      "Variant glow needs three color components and a supported intensity."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant.material",
    "messages": [
      "Choose a supported variant material route."
    ],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant.placement",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant.translucency",
    "messages": [],
    "sources": [
      "cdmw/domain/new_item/authoring_rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "variant_placement_not_applied",
    "messages": [
      "Apply the imported placement for {state.appearance.model_path} in step 3."
    ],
    "sources": [
      "cdmw/ui/new_item/controller.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "{field_name}.shape",
    "messages": [
      "Localisation keys are short ASCII identifiers."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "{field_name}.taken",
    "messages": [
      "Localisation key {value} already exists."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": []
  },
  {
    "group": "new_item",
    "code": "{field_name}.unconventional",
    "messages": [
      "The game derives this key from the item key; a different key is carried in the row but the name stays blank in game. Leave it unset to allocate the derived one."
    ],
    "sources": [
      "cdmw/domain/new_item/rules.py"
    ],
    "severity": [
      "warning"
    ]
  },
  {
    "group": "panels",
    "code": "mesh_editor_ui_state_invariant_failed",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/ui_state_reducer.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "native_compare_snapshot_unavailable",
    "messages": [
      "native mesh editor compare summary unavailable; Python mesh state is stale"
    ],
    "sources": [
      "cdmw/services/mesh_service_uv.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "native_skeleton_snapshot_unavailable",
    "messages": [
      "native mesh editor skeleton summary unavailable; Python mesh state is stale"
    ],
    "sources": [
      "cdmw/services/mesh_service_rigging.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "native_uv_snapshot_unavailable",
    "messages": [
      "native mesh editor UV summary unavailable; Python mesh state is stale"
    ],
    "sources": [
      "cdmw/services/mesh_service_uv.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "native_workspace_snapshot_unavailable",
    "messages": [
      "native mesh editor workspace summary failed; Python mesh state is stale"
    ],
    "sources": [
      "cdmw/services/mesh_service_uv.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "rebuild_cancelled",
    "messages": [],
    "sources": [
      "cdmw/ui/mesh_editor/tab_reports.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "rebuild_worker_failed",
    "messages": [],
    "sources": [
      "cdmw/ui/mesh_editor/tab_reports.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "unexpected_{panel_name.value}_summary_failure",
    "messages": [],
    "sources": [
      "cdmw/ui/mesh_editor/tab_panel_state.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "validation_worker_failed",
    "messages": [],
    "sources": [
      "cdmw/ui/mesh_editor/tab_reports.py"
    ],
    "severity": []
  },
  {
    "group": "panels",
    "code": "{panel_name.value}_provider_unavailable",
    "messages": [],
    "sources": [
      "cdmw/ui/mesh_editor/tab_panel_state.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_BOUNDS_EXCEED_SOURCE",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_CONTRACT_UNSUPPORTED",
    "messages": [
      "Topology {label} {parsed} is negative."
    ],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED",
    "messages": [
      "A topology result must keep at least one triangle.",
      "An empty topology result cannot retain triangles."
    ],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_FACE_ORIGIN_INVALID",
    "messages": [
      "Output triangle {position} names pre-operation face {face_index} outside [0, {previous.output_face_count})."
    ],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_OPERATION_NOT_REBUILDABLE",
    "messages": [
      "Topology provenance was submitted without an authorized topology change."
    ],
    "sources": [
      "cdmw/domain/mesh/asset.py",
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": [
      "fatal"
    ]
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_PAC_INDEX_LIMIT_EXCEEDED",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_PROTECTED_BYTES_DIVERGE",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_PROVENANCE_REQUIRED",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_REVISION_DISCONTINUOUS",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED",
    "messages": [],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  },
  {
    "group": "topology",
    "code": "TOPOLOGY_VERTEX_ORIGIN_INVALID",
    "messages": [
      "Output vertex {index} has more than one blend derivation.",
      "Output vertex {output_index} copies pre-operation vertex {copy_index} outside [0, {previous_count}).",
      "Output vertex {output_index} has neither a copy source nor a blend derivation.",
      "Output vertex {output_index} is both a copy and a blend derivation.",
      "Topology weight {value} is not a real number.",
      "Topology weight {value} must be finite and strictly positive.",
      "Vertex blend factor {parsed_factor} must lie strictly between 0 and 1.",
      "Vertex blend for output vertex {index} references a pre-operation vertex outside [0, {previous_count}).",
      "Vertex blend must carry index, left, right, and factor; got {len(values)} value(s).",
      "Vertex blend names output vertex {index} outside [0, {output_vertex_count}).",
      "Vertex blend(s) {missing} do not correspond to a derived output vertex.",
      "Vertex origin has no parents.",
      "Vertex origin has {len(raw_parents)} parent(s) but {len(raw_weights)} weight(s).",
      "Vertex origin merged to a non-positive parent weight.",
      "Vertex origin normalization produced a non-positive weight.",
      "Vertex origin parent {parent} is outside the original vertex range [0, {original_vertex_count}).",
      "Vertex origin weights do not sum to a positive total.",
      "Vertex origin weights sum to {math.fsum(normalized)} after normalization."
    ],
    "sources": [
      "cdmw/domain/mesh/topology.py"
    ],
    "severity": []
  }
]
