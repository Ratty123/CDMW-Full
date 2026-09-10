// Keep protocol/cache identities in UTF-8 and extend paths only for Windows I/O.
std::string json_escape(const std::string& value);

static fs::path utf8_path(const std::string& value) {
    return fs::u8path(value);
}

static std::string path_utf8(const fs::path& path) {
    const auto bytes = path.u8string();
    std::string value(bytes.begin(), bytes.end());
#ifdef _WIN32
    std::string prefix = value.substr(0, 8);
    std::transform(prefix.begin(), prefix.end(), prefix.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    if (prefix == "\\\\?\\unc\\") return "\\\\" + value.substr(8);
    if (value.starts_with("\\\\?\\") && value.size() > 6 && value[5] == ':') return value.substr(4);
#endif
    return value;
}

static fs::path native_file_path(const fs::path& path) {
#ifdef _WIN32
    if (path.empty()) return path;
    const auto original = path.wstring();
    if (original.starts_with(L"\\\\?\\") || original.starts_with(L"\\\\.\\")) return path;
    auto absolute = fs::absolute(path).lexically_normal();
    const auto value = absolute.make_preferred().wstring();
    if (value.starts_with(L"\\\\")) return fs::path(L"\\\\?\\UNC\\" + value.substr(2));
    return fs::path(L"\\\\?\\" + value);
#else
    return path;
#endif
}

static std::string file_error_message(const std::error_code& code) {
#ifdef _WIN32
    if (code.category() == std::system_category()) {
        wchar_t* message = nullptr;
        const auto length = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM
            | FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, static_cast<DWORD>(code.value()), 0,
            reinterpret_cast<wchar_t*>(&message), 0, nullptr);
        if (length && message) {
            auto text = cdmw_native_diag::wide_to_utf8_diag(std::wstring(message, length));
            LocalFree(message);
            while (!text.empty() && (text.back() == '\r' || text.back() == '\n')) text.pop_back();
            return text;
        }
    }
#endif
    return code.message();
}

struct FileAccessError : std::runtime_error {
    fs::path path;
    std::error_code code;
    std::string operation;

    FileAccessError(const fs::path& source, std::error_code error, const std::string& action)
        : std::runtime_error("could not " + action + " " + path_utf8(source) + ": " + file_error_message(error)
              + " (" + error.category().name() + " error " + std::to_string(error.value())
              + "; path length " + std::to_string(source.native().size()) + ")"),
          path(source), code(error), operation(action) {}
};

[[noreturn]] static void throw_file_error(const std::string& operation, const fs::path& path) {
    const int saved_errno = errno;
#ifdef _WIN32
    unsigned long windows_error = 0;
    _get_doserrno(&windows_error);
    if (windows_error != 0) {
        throw FileAccessError(path, std::error_code(static_cast<int>(windows_error), std::system_category()), operation);
    }
#endif
    throw FileAccessError(path, std::error_code(saved_errno, std::generic_category()), operation);
}

// The report carries the OS cause separately from its human-readable message.
static std::string file_error_fields(const std::exception& error) {
    fs::path path;
    std::error_code code;
    std::string operation;
    if (const auto* access = dynamic_cast<const FileAccessError*>(&error)) {
        path = access->path;
        code = access->code;
        operation = access->operation;
    } else if (const auto* filesystem = dynamic_cast<const fs::filesystem_error*>(&error)) {
        path = filesystem->path1();
        code = filesystem->code();
        operation = "access";
    } else {
        return {};
    }
    std::string kind = "io_error";
    bool retryable = true;
    if (code == std::errc::no_such_file_or_directory) kind = "missing";
    else if (code == std::errc::permission_denied) kind = "access_denied";
    else if (code == std::errc::filename_too_long) kind = "path_too_long";
    else if (code == std::errc::not_a_directory || code == std::errc::invalid_argument) kind = "invalid_path";
#ifdef _WIN32
    if (code.category() == std::system_category()) {
        if (code.value() == ERROR_FILE_NOT_FOUND || code.value() == ERROR_PATH_NOT_FOUND) kind = "missing";
        else if (code.value() == ERROR_ACCESS_DENIED) kind = "access_denied";
        else if (code.value() == ERROR_FILENAME_EXCED_RANGE) kind = "path_too_long";
        else if (code.value() == ERROR_INVALID_NAME || code.value() == ERROR_DIRECTORY) kind = "invalid_path";
        else if (code.value() == ERROR_SHARING_VIOLATION || code.value() == ERROR_LOCK_VIOLATION) kind = "locked";
    }
#endif
    if (kind == "missing" || kind == "access_denied" || kind == "path_too_long" || kind == "invalid_path") retryable = false;
    return "\"file_error\":{\"kind\":\"" + kind + "\",\"path\":\"" + json_escape(path_utf8(path))
        + "\",\"operation\":\"" + operation + "\",\"os_error\":" + std::to_string(code.value())
        + ",\"os_error_category\":\"" + code.category().name() + "\",\"path_length\":"
        + std::to_string(utf8_path(path_utf8(path)).native().size()) + "},\"retryable\":" + (retryable ? "true," : "false,");
}

static void run_path_io_self_test() {
#ifdef _WIN32
    const auto local = native_file_path(utf8_path("C:/CDMW/a/../b.pac"));
    if (local.wstring() != L"\\\\?\\C:\\CDMW\\b.pac") throw std::runtime_error("local extended path conversion failed");
    const auto unc = native_file_path(utf8_path("\\\\server\\share\\folder\\model.pac"));
    if (unc.wstring() != L"\\\\?\\UNC\\server\\share\\folder\\model.pac") throw std::runtime_error("UNC extended path conversion failed");
    if (native_file_path(unc) != unc || native_file_path(local) != local) throw std::runtime_error("extended paths were prefixed twice");
    if (path_utf8(unc) != "\\\\server\\share\\folder\\model.pac") throw std::runtime_error("extended path leaked into protocol");
    const FileAccessError length_error(utf8_path("C:/model.pac"),
        std::error_code(ERROR_FILENAME_EXCED_RANGE, std::system_category()), "open");
    const auto fields = file_error_fields(length_error);
    if (fields.find("path_too_long") == std::string::npos || fields.find("\"retryable\":false") == std::string::npos) {
        throw std::runtime_error("Windows path length error classification failed");
    }
#endif
}
