#include "preview_core.hpp"

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    return cdmw_preview_core::run_cli_utf16(argc, argv);
}
#else
int main(int argc, char** argv) {
    return cdmw_preview_core::run_cli(argc, argv);
}
#endif
