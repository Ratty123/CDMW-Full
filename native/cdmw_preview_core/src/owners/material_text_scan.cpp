// Linear scans over material sidecar text.
//
// A static model's companion (.pam or .pamlod) is megabytes of binary mesh data that
// is read as a material sidecar for the texture names it holds. Each scan here gives
// exactly the result of the regular expression named beside it, without running a
// backtracking matcher from every byte. material_text_scan_self_tests.cpp checks
// every scan against that expression.
//
// Case is folded for A-Z only, which is what std::regex does with the "C" locale this
// process runs in.

static inline char ascii_fold(char ch) {
    return (ch >= 'A' && ch <= 'Z') ? static_cast<char>(ch + ('a' - 'A')) : ch;
}

// The six characters std::regex's \s matches for a char in the "C" locale.
static inline bool regex_space(char ch) {
    return ch == ' ' || (ch >= '\t' && ch <= '\r');
}

// `literal` is lower case.
static bool ascii_iequals_at(const std::string& text, size_t position, std::string_view literal) {
    if (position > text.size() || text.size() - position < literal.size()) return false;
    for (size_t offset = 0; offset < literal.size(); ++offset) {
        if (ascii_fold(text[position + offset]) != literal[offset]) return false;
    }
    return true;
}

// std::string::find on a lower-cased copy of `text`, without the copy. `needle` is
// lower case and not empty.
static size_t find_ascii_icase(const std::string& text, std::string_view needle, size_t start) {
    if (needle.empty() || text.size() < needle.size()) return std::string::npos;
    const size_t last = text.size() - needle.size();
    const char first = needle.front();
    const bool first_has_case = first >= 'a' && first <= 'z';
    for (size_t position = start; position <= last; ++position) {
        if (!first_has_case) {
            const void* hit = std::memchr(text.data() + position, first, last - position + 1);
            if (hit == nullptr) return std::string::npos;
            position = static_cast<size_t>(static_cast<const char*>(hit) - text.data());
        } else if (ascii_fold(text[position]) != first) {
            continue;
        }
        if (ascii_iequals_at(text, position, needle)) return position;
    }
    return std::string::npos;
}

// The number of matches std::sregex_iterator finds for `a|b|c` with icase, where every
// alternative is a literal (lower case here): leftmost first, the earlier alternative
// winning at one position, the next search starting where the match ended.
static int count_icase_literals(const std::string& text, std::initializer_list<std::string_view> literals) {
    bool starts[256] = {};
    for (const std::string_view literal : literals) {
        starts[static_cast<unsigned char>(literal.front())] = true;
    }
    int count = 0;
    for (size_t position = 0; position < text.size(); ++position) {
        if (!starts[static_cast<unsigned char>(ascii_fold(text[position]))]) continue;
        for (const std::string_view literal : literals) {
            if (ascii_iequals_at(text, position, literal)) {
                ++count;
                position += literal.size() - 1;
                break;
            }
        }
    }
    return count;
}

static inline bool path_token_char(char ch) {
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')
        || ch == '_' || ch == '.' || ch == '/' || ch == '\\' || ch == '-';
}

// Matches of `([A-Za-z0-9_./\\-]+\.(?:ext|ext))` with icase, in order. Within one
// unbroken run of those characters the greedy `+` first takes the whole run and then
// gives characters back, so the single match of a run starts at the run and ends
// after its last `.ext`, provided at least one character precedes that dot. Every
// extension is three lower-case letters. `visit` returns false to stop.
template <typename Visit>
static void scan_path_tokens(
    const std::string& text,
    std::initializer_list<std::string_view> extensions,
    Visit visit
) {
    size_t position = 0;
    while (position < text.size()) {
        if (!path_token_char(text[position])) {
            ++position;
            continue;
        }
        const size_t run_start = position;
        while (position < text.size() && path_token_char(text[position])) ++position;
        const size_t run_end = position;
        if (run_end - run_start < 5) continue;
        for (size_t dot = run_end - 4; dot > run_start; --dot) {
            if (text[dot] != '.') continue;
            bool matched = false;
            for (const std::string_view extension : extensions) {
                if (ascii_iequals_at(text, dot + 1, extension)) {
                    matched = true;
                    break;
                }
            }
            if (!matched) continue;
            if (!visit(run_start, dot + 4)) return;
            break;
        }
    }
}

// Group 1 of the first match of
//   (?:^|[\s<])(?:_materialName|MaterialName|TechniqueName)="([^"]+)"
// with icase, or an empty string.
static std::string first_material_name_attribute(const std::string& text) {
    static constexpr std::string_view names[] = {"_materialname", "materialname", "techniquename"};
    size_t search = 0;
    while (true) {
        const size_t equals = text.find("=\"", search);
        if (equals == std::string::npos) return "";
        search = equals + 1;
        for (const std::string_view name : names) {
            if (equals < name.size()) continue;
            const size_t name_start = equals - name.size();
            if (!ascii_iequals_at(text, name_start, name)) continue;
            if (name_start != 0 && !regex_space(text[name_start - 1]) && text[name_start - 1] != '<') continue;
            const size_t value_start = equals + 2;
            const size_t close = text.find('"', value_start);
            if (close == std::string::npos) return "";  // no later value can close either
            if (close == value_start) break;            // an empty value is not a match
            return text.substr(value_start, close - value_start);
        }
    }
}

static size_t shader_version_suffix_end(const std::string& text, size_t position) {
    if (!ascii_iequals_at(text, position, "_ver")) return position;
    size_t end = position + 4;
    while (end < text.size() && text[end] >= '0' && text[end] <= '9') ++end;
    return end > position + 4 ? end : position;
}

// The first match of
//   (SkinnedMesh(?:Skin(?:Wrinkle)?|Standard(?:_Ver[0-9]+)?|Cloth(?:_Ver[0-9]+)?|Hair|Fur(?:_Ver[0-9]+)?|AnimalHair)|MultiTextured|Standard)
// with icase, or an empty string.
static std::string first_shader_family_token(const std::string& text) {
    for (size_t position = 0; position < text.size(); ++position) {
        const char first = ascii_fold(text[position]);
        if (first == 'm') {
            if (ascii_iequals_at(text, position, "multitextured")) return text.substr(position, 13);
            continue;
        }
        if (first != 's') continue;
        if (ascii_iequals_at(text, position, "skinnedmesh")) {
            const size_t inner = position + 11;
            size_t end = std::string::npos;
            if (ascii_iequals_at(text, inner, "skin")) {
                end = inner + 4;
                if (ascii_iequals_at(text, end, "wrinkle")) end += 7;
            } else if (ascii_iequals_at(text, inner, "standard")) {
                end = shader_version_suffix_end(text, inner + 8);
            } else if (ascii_iequals_at(text, inner, "cloth")) {
                end = shader_version_suffix_end(text, inner + 5);
            } else if (ascii_iequals_at(text, inner, "hair")) {
                end = inner + 4;
            } else if (ascii_iequals_at(text, inner, "fur")) {
                end = shader_version_suffix_end(text, inner + 3);
            } else if (ascii_iequals_at(text, inner, "animalhair")) {
                end = inner + 10;
            }
            if (end != std::string::npos) return text.substr(position, end - position);
        } else if (ascii_iequals_at(text, position, "standard")) {
            return text.substr(position, 8);
        }
    }
    return "";
}

// Every match of `<[^!?/][^>]*>`, in order.
static std::vector<std::string> scan_xml_open_tags(const std::string& text) {
    std::vector<std::string> tags;
    size_t search = 0;
    while (true) {
        const size_t open = text.find('<', search);
        if (open == std::string::npos || open + 1 >= text.size()) break;
        const char next = text[open + 1];
        if (next == '!' || next == '?' || next == '/') {
            search = open + 1;
            continue;
        }
        const size_t close = text.find('>', open + 2);
        if (close == std::string::npos) break;  // no later tag can close either
        tags.push_back(text.substr(open, close + 1 - open));
        search = close + 1;
    }
    return tags;
}
