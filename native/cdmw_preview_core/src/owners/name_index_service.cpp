
static std::vector<std::string> name_search_tokens(const std::string& text) {
    std::vector<std::string> tokens;
    std::string current;
    for (unsigned char raw_ch : text) {
        if (std::isalnum(raw_ch)) {
            current.push_back(static_cast<char>(std::tolower(raw_ch)));
        } else if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) tokens.push_back(current);
    return tokens;
}

static const std::vector<std::pair<std::string, std::vector<std::string>>>& name_search_token_aliases() {
    static const std::vector<std::pair<std::string, std::vector<std::string>>> aliases = {
        {"armor", {"armour"}},
        {"armour", {"armor"}},
        {"helmet", {"helm"}},
        {"helm", {"helmet"}},
        {"pickaxe", {"axe"}},
        {"crossbow", {"bow"}},
        {"treasurebox", {"treasure", "box"}},
        {"campfire", {"camp", "fire"}},
        {"candlestick", {"candle", "lamp"}},
    };
    return aliases;
}

static void add_name_search_token(
    std::unordered_map<std::string, std::vector<std::uint32_t>>& token_rows,
    const std::string& token,
    std::uint32_t row
) {
    const std::string normalized = lower_copy(token);
    if (normalized.size() <= 1) return;
    token_rows[normalized].push_back(row);
    for (const auto& [source, aliases] : name_search_token_aliases()) {
        if (source.size() > 4 && normalized.find(source) != std::string::npos && source != normalized) {
            token_rows[source].push_back(row);
        }
        if (normalized == source || (source.size() > 4 && normalized.find(source) != std::string::npos)) {
            for (const std::string& alias : aliases) {
                if (alias.size() > 1) token_rows[alias].push_back(row);
            }
        }
    }
}

static std::vector<std::string> split_tsv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    for (char ch : line) {
        if (ch == '\t') {
            fields.push_back(current);
            current.clear();
        } else {
            current.push_back(ch);
        }
    }
    fields.push_back(current);
    return fields;
}

template <typename T>
static void write_pod(std::ofstream& out, T value) {
    out.write(reinterpret_cast<const char*>(&value), sizeof(T));
}

static void write_name_index_progress(
    const fs::path& progress_path,
    const std::string& stage,
    std::uint64_t processed_entries,
    std::uint64_t token_count = 0,
    std::uint64_t posting_count = 0
) {
    if (progress_path.empty()) return;
    try {
        fs::create_directories(progress_path.parent_path());
        std::ofstream out(progress_path, std::ios::binary | std::ios::trunc);
        if (!out) return;
        out << "{"
            << "\"stage\":\"" << json_escape(stage) << "\","
            << "\"processed_entries\":" << processed_entries << ","
            << "\"token_count\":" << token_count << ","
            << "\"posting_count\":" << posting_count
            << "}";
    } catch (...) {
    }
}

int run_name_index_job(
    const fs::path& input_tsv_path,
    const fs::path& output_bin_path,
    const fs::path& report_path,
    const fs::path& progress_path = {}
) {
    const auto started = std::chrono::steady_clock::now();
    std::uint32_t entry_count = 0;
    std::unordered_map<std::string, std::vector<std::uint32_t>> token_rows;
    try {
        write_name_index_progress(progress_path, "tokenize", 0, 0, 0);
        std::ifstream in(input_tsv_path, std::ios::binary);
        if (!in) throw std::runtime_error("could not open name-search input TSV");
        std::string line;
        std::uint64_t processed_lines = 0;
        while (std::getline(in, line)) {
            const std::vector<std::string> fields = split_tsv_line(line);
            if (fields.size() < 3) continue;
            std::uint32_t row = 0;
            try {
                row = static_cast<std::uint32_t>(std::stoul(fields[0]));
            } catch (...) {
                continue;
            }
            entry_count = std::max(entry_count, row + 1u);
            std::string text = fields[1] + " " + fields[2];
            if (fields.size() >= 4 && !fields[3].empty()) {
                text += " ";
                text += fields[3];
            }
            std::set<std::string> seen_tokens;
            for (const std::string& token : name_search_tokens(text)) {
                if (!seen_tokens.insert(token).second) continue;
                add_name_search_token(token_rows, token, row);
            }
            ++processed_lines;
            if (processed_lines == 1 || processed_lines % 50000u == 0) {
                write_name_index_progress(progress_path, "tokenize", processed_lines, token_rows.size(), 0);
            }
        }

        write_name_index_progress(progress_path, "write", entry_count, token_rows.size(), 0);
        fs::create_directories(output_bin_path.parent_path());
        std::ofstream out(output_bin_path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("could not write name-search output binary");
        const char magic[8] = {'C', 'D', 'N', 'I', 'D', 'X', '1', '\0'};
        out.write(magic, sizeof(magic));
        write_pod<std::uint32_t>(out, 1u);
        std::vector<std::string> keys;
        keys.reserve(token_rows.size());
        for (const auto& [token, _rows] : token_rows) {
            if (!token.empty() && token.size() <= 65535u) keys.push_back(token);
        }
        std::sort(keys.begin(), keys.end());
        write_pod<std::uint32_t>(out, entry_count);
        write_pod<std::uint32_t>(out, static_cast<std::uint32_t>(keys.size()));
        std::uint64_t posting_count = 0;
        std::uint64_t processed_tokens = 0;
        for (const std::string& token : keys) {
            std::vector<std::uint32_t>& rows = token_rows[token];
            std::sort(rows.begin(), rows.end());
            rows.erase(std::unique(rows.begin(), rows.end()), rows.end());
            const auto token_size = static_cast<std::uint16_t>(token.size());
            write_pod<std::uint16_t>(out, token_size);
            out.write(token.data(), token.size());
            write_pod<std::uint32_t>(out, static_cast<std::uint32_t>(rows.size()));
            if (!rows.empty()) {
                out.write(reinterpret_cast<const char*>(rows.data()), static_cast<std::streamsize>(rows.size() * sizeof(std::uint32_t)));
                posting_count += rows.size();
            }
            ++processed_tokens;
            if (processed_tokens == 1 || processed_tokens % 25000u == 0 || processed_tokens == keys.size()) {
                write_name_index_progress(progress_path, "write", entry_count, processed_tokens, posting_count);
            }
        }
        out.close();
        if (!out) throw std::runtime_error("name-search output binary write failed");
        write_name_index_progress(progress_path, "complete", entry_count, keys.size(), posting_count);
        const double elapsed_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
        std::ostringstream report;
        report << "{"
               << "\"status\":\"ok\","
               << "\"backend\":\"cdmw_preview_core_0.1\","
               << "\"operation\":\"name_index\","
               << "\"entry_count\":" << entry_count << ","
               << "\"token_count\":" << keys.size() << ","
               << "\"posting_count\":" << posting_count << ","
               << "\"elapsed_ms\":" << elapsed_ms << ","
               << "\"output_path\":\"" << json_escape(output_bin_path.string()) << "\""
               << "}";
        write_text(report_path, report.str());
        return 0;
    } catch (const std::exception& exc) {
        std::ostringstream report;
        report << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"operation\":\"name_index\",\"message\":\""
               << json_escape(exc.what()) << "\"}";
        try { write_text(report_path, report.str()); } catch (...) {}
        write_name_index_progress(progress_path, "error", entry_count, token_rows.size(), 0);
        return 2;
    }
}

std::string extract_line_path(const std::string& line, const std::string& key) {
    std::string value = find_string_value(line, key);
    if (!value.empty()) return value;
    return {};
}

int run_service() {
    cdmw_native_diag::event("service_start");
    std::cout << "{\"event\":\"ready\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        const std::string lowered = lower_copy(line);
        if (lowered.find("\"shutdown\"") != std::string::npos) {
            cdmw_native_diag::event("service_shutdown");
            std::cout << "{\"event\":\"closed\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            return 0;
        }
        if (lowered.find("\"ping\"") != std::string::npos) {
            cdmw_native_diag::event("service_ping");
            std::cout << "{\"event\":\"pong\",\"backend\":\"cdmw_preview_core_0.1\"}" << std::endl;
            continue;
        }
        const std::string job_path = extract_line_path(line, "job_path");
        const std::string report_path = extract_line_path(line, "report_path");
        if (!job_path.empty() && !report_path.empty()) {
            ++g_service_job_count;
            cdmw_native_diag::event(
                "service_job_dispatch",
                {
                    {"job_path", job_path},
                    {"report_path", report_path},
                    {"service_job_count", std::to_string(g_service_job_count)}
                });
            const int exit_code = run_preview_job(fs::path(job_path), fs::path(report_path));
            std::cout << "{\"status\":\"" << (exit_code == 0 ? "ok" : "error")
                      << "\",\"backend\":\"cdmw_preview_core_0.1\",\"report_path\":\""
                      << json_escape(report_path) << "\",\"exit_code\":" << exit_code << "}" << std::endl;
            continue;
        }
        cdmw_native_diag::event("service_unknown_command");
        std::cout << "{\"status\":\"error\",\"backend\":\"cdmw_preview_core_0.1\",\"message\":\"unknown command\"}" << std::endl;
    }
    cdmw_native_diag::event("service_closed_stdin");
    return 0;
}
