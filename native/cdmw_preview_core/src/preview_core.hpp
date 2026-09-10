#pragma once

namespace cdmw_preview_core {

int run_cli(int argc, char** argv);
#ifdef _WIN32
int run_cli_utf16(int argc, wchar_t** argv);
#endif

}  // namespace cdmw_preview_core
