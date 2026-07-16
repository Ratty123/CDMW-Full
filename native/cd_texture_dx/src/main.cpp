#include "texture_tool_internal.h"

#include <Windows.h>
#include <objbase.h>

#include <cstdio>
#include <exception>
#include <filesystem>
#include <iostream>
#include <string>

#include "../../common/native_diagnostics.h"

namespace fs = std::filesystem;

struct ComInitScope {
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool needs_uninit = (hr == S_OK || hr == S_FALSE);

    ~ComInitScope() {
        if (needs_uninit) {
            CoUninitialize();
        }
    }
};

static int run_command(int argc, wchar_t** argv) {
    ComInitScope com_init;
    if (argc >= 2 && std::wstring(argv[1]) == L"self-test") {
        if (!json_parser_self_test()) {
            cdmw_native_diag::event("self_test_error", {{"component", "json_parser"}});
            std::cout << "{\"event\":\"self_test\",\"ok\":false,\"protocol_version\":2,\"backend\":\"directxtex_native_0.2\",\"component\":\"json_parser\"}\n";
            return 2;
        }
        std::string failed_component;
        if (!texture_codec_self_test(failed_component)) {
            cdmw_native_diag::event("self_test_error", {{"component", failed_component}});
            std::cout << "{\"event\":\"self_test\",\"ok\":false,\"protocol_version\":2,\"backend\":\"directxtex_native_0.2\",\"component\":\""
                << json_escape(failed_component) << "\"}\n";
            return 2;
        }
        cdmw_native_diag::event("self_test_ok");
        std::cout << "{\"event\":\"self_test\",\"ok\":true,\"protocol_version\":2,\"backend\":\"directxtex_native_0.2\",\"coverage\":[\"bc7_linear\",\"bc7_srgb\",\"separate_alpha\",\"preserve_coverage\",\"selected_mip\",\"gray16\"]}\n";
        return 0;
    }
    if (argc >= 3 && std::wstring(argv[1]) == L"inspect-json") {
        return inspect_json(argv[2]);
    }
    if (argc >= 4 && std::wstring(argv[1]) == L"batch-preview-json") {
        return batch_preview_json_guarded(fs::path(argv[2]), fs::path(argv[3]));
    }
    if (argc >= 4 && std::wstring(argv[1]) == L"batch-encode-json") {
        return batch_encode_json_guarded(fs::path(argv[2]), fs::path(argv[3]));
    }
    std::cerr << "usage: cd-texture-dx self-test | inspect-json <dds> | batch-preview-json <job.json> <report.json> | batch-encode-json <job.json> <report.json>\n";
    return 1;
}

int wmain(int argc, wchar_t** argv) {
    try {
        CommonArgs common_args = parse_common_args(argc, argv);
        cdmw_native_diag::init("cd-texture-dx", common_args.crash_dir, common_args.diagnostic_log);
        const std::string command = argc >= 2 && argv[1] ? wide_to_utf8(argv[1]) : "usage";
        cdmw_native_diag::event("command_dispatch", {{"command", command}});
        return run_command(argc, argv);
    } catch (const std::exception& exc) {
        record_caught_exception("native_cxx_exception_caught", "command_dispatch", exc.what());
        std::fputs("{\"status\":\"error\",\"backend\":\"directxtex_native_0.2\",\"message\":\"native C++ exception caught\"}\n", stdout);
        return 4;
    } catch (...) {
        record_caught_exception("native_cxx_exception_caught", "command_dispatch", "unknown native exception");
        std::fputs("{\"status\":\"error\",\"backend\":\"directxtex_native_0.2\",\"message\":\"unknown native exception caught\"}\n", stdout);
        return 4;
    }
}
