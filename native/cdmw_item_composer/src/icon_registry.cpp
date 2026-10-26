// item_icon_registry.parse_icon_registry over the XML subset this port reproduces exactly.
//
// Python validates the whole file with expat. This reader accepts flat elements, comments,
// character data and attributes, and refuses with Unsupported any well-formed construct it
// does not model (entity and character references, CDATA, processing instructions,
// declarations, non-ASCII names) so the result never silently differs from Python's.
#include "composer_internal.hpp"

namespace cdmw::compose::detail {
namespace {

[[noreturn]] void unsupported(const std::string& reason) { throw Unsupported("icon registry: " + reason); }
[[noreturn]] void invalid(const std::string& reason) { throw FormatError(reason); }

bool xml_space(std::uint8_t c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
bool name_start(std::uint8_t c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == ':'; }
bool name_char(std::uint8_t c) { return name_start(c) || (c >= '0' && c <= '9') || c == '.' || c == '-'; }

// Every code point must be an XML Char.
void require_xml_chars(const Bytes& raw, std::size_t from) {
    if (!valid_utf8(raw.data() + from, raw.size() - from)) unsupported("not UTF-8");
    for (std::size_t at = from; at < raw.size();) {
        const auto lead = raw[at];
        std::uint32_t code;
        std::size_t length;
        if (lead < 0x80) { code = lead; length = 1; }
        else if (lead < 0xE0) { code = lead & 0x1Fu; length = 2; }
        else if (lead < 0xF0) { code = lead & 0x0Fu; length = 3; }
        else { code = lead & 0x07u; length = 4; }
        for (std::size_t i = 1; i < length; ++i) code = (code << 6) | (raw[at + i] & 0x3Fu);
        const bool allowed = code == 0x9 || code == 0xA || code == 0xD || (code >= 0x20 && code <= 0xD7FF) ||
                             (code >= 0xE000 && code <= 0xFFFD) || code >= 0x10000;
        if (!allowed) unsupported("a character XML does not allow");
        at += length;
    }
}

bool ascii(const std::string& text) {
    return std::all_of(text.begin(), text.end(), [](char c) { return static_cast<unsigned char>(c) < 0x80; });
}
std::string lower(std::string text) {
    for (auto& c : text) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return text;
}
std::string strip_spaces(const std::string& text) {
    const auto first = text.find_first_not_of(' ');
    return first == std::string::npos ? std::string() : text.substr(first, text.find_last_not_of(' ') - first + 1);
}

class Reader {
public:
    explicit Reader(const Bytes& raw) : raw_(raw) {}

    IconRegistry parse() {
        const std::size_t bom = starts_with(raw_, "\xEF\xBB\xBF") ? 3 : 0;
        require_xml_chars(raw_, bom);
        at_ = bom;
        while (at_ < raw_.size()) {
            if (raw_[at_] != '<') character_data();
            else if (ahead("<!--")) comment();
            else if (ahead("<!") || ahead("<?")) unsupported("declarations, CDATA and processing instructions");
            else if (ahead("</")) end_tag();
            else start_tag();
        }
        if (!open_.empty()) invalid("invalid flat icon registry XML: unclosed element");
        if (registry_.textures.empty()) invalid("the data holds no <Texture> elements; not the icon registry");
        std::size_t from = 0;
        for (const auto& [begin, finish] : spans_) {
            registry_.remainder.insert(registry_.remainder.end(), raw_.begin() + static_cast<std::ptrdiff_t>(from), raw_.begin() + static_cast<std::ptrdiff_t>(begin));
            from = finish;
        }
        registry_.remainder.insert(registry_.remainder.end(), raw_.begin() + static_cast<std::ptrdiff_t>(from), raw_.end());
        const auto strip = [](std::uint8_t c) { return c == '\r' || c == '\n' || c == '\t' || c == ' '; };
        auto& rest = registry_.remainder;
        while (!rest.empty() && strip(rest.back())) rest.pop_back();
        rest.erase(rest.begin(), std::find_if_not(rest.begin(), rest.end(), strip));
        return std::move(registry_);
    }

private:
    bool ahead(std::string_view text) const {
        return raw_.size() - at_ >= text.size() && std::equal(text.begin(), text.end(), raw_.begin() + static_cast<std::ptrdiff_t>(at_));
    }
    std::uint8_t peek() const {
        if (at_ >= raw_.size()) invalid("invalid flat icon registry XML: the file ends inside a tag");
        return raw_[at_];
    }
    std::size_t skip_space() {
        const auto from = at_;
        while (at_ < raw_.size() && xml_space(raw_[at_])) ++at_;
        return at_ - from;
    }
    std::string name() {
        const auto from = at_;
        if (at_ < raw_.size() && raw_[at_] >= 0x80) unsupported("non-ASCII names");
        if (!name_start(peek())) unsupported("a name XML may not start that way");
        while (at_ < raw_.size() && name_char(raw_[at_])) ++at_;
        if (at_ < raw_.size() && raw_[at_] >= 0x80) unsupported("non-ASCII names");
        return std::string(raw_.begin() + static_cast<std::ptrdiff_t>(from), raw_.begin() + static_cast<std::ptrdiff_t>(at_));
    }
    void character_data() {
        const auto end = static_cast<std::size_t>(std::find(raw_.begin() + static_cast<std::ptrdiff_t>(at_), raw_.end(), '<') - raw_.begin());
        const Bytes text(raw_.begin() + static_cast<std::ptrdiff_t>(at_), raw_.begin() + static_cast<std::ptrdiff_t>(end));
        if (std::find(text.begin(), text.end(), '&') != text.end()) unsupported("entity and character references");
        if (contains(text, "]]>")) unsupported("']]>' in character data");
        at_ = end;
    }
    void comment() {
        const auto body = at_ + 4;
        const auto found = std::search(raw_.begin() + static_cast<std::ptrdiff_t>(body), raw_.end(), std::begin("-->"), std::end("-->") - 1);
        if (found == raw_.end()) unsupported("an unterminated comment");
        const Bytes text(raw_.begin() + static_cast<std::ptrdiff_t>(body), found);
        if (contains(text, "--") || (!text.empty() && text.back() == '-')) unsupported("'--' inside a comment");
        at_ = static_cast<std::size_t>(found - raw_.begin()) + 3;
    }
    void end_tag() {
        at_ += 2;
        const auto tag = name();
        skip_space();
        if (peek() != '>') unsupported("an end tag that does not close");
        ++at_;
        if (open_.empty()) unsupported("closing the registry's synthetic root");
        if (open_.back() != tag) invalid("invalid flat icon registry XML: mismatched tag");
        open_.pop_back();
    }
    void start_tag() {
        const auto begin = at_;
        ++at_;
        const auto tag = name();
        std::map<std::string, std::string> attributes;
        bool closed = false;
        for (;;) {
            const auto space = skip_space();
            const auto next = peek();
            if (next == '/') {
                ++at_;
                if (peek() != '>') unsupported("'/' without '>'");
                ++at_;
                closed = true;
                break;
            }
            if (next == '>') {
                ++at_;
                break;
            }
            if (!space) unsupported("attributes without separating white space");
            auto key = name();
            skip_space();
            if (peek() != '=') unsupported("an attribute without a value");
            ++at_;
            skip_space();
            const auto quote = peek();
            if (quote != '"' && quote != '\'') unsupported("an unquoted attribute value");
            const auto end = std::find(raw_.begin() + static_cast<std::ptrdiff_t>(at_ + 1), raw_.end(), quote);
            if (end == raw_.end()) invalid("invalid flat icon registry XML: unterminated attribute value");
            std::string value(raw_.begin() + static_cast<std::ptrdiff_t>(at_ + 1), end);
            at_ = static_cast<std::size_t>(end - raw_.begin()) + 1;
            if (value.find('&') != std::string::npos || value.find('<') != std::string::npos) unsupported("references or '<' in attribute values");
            // expat normalizes attribute values: line ends, tabs and newlines become spaces.
            value = replace_all(value, "\r\n", " ");
            for (auto& c : value) if (c == '\r' || c == '\n' || c == '\t') c = ' ';
            if (!attributes.emplace(std::move(key), std::move(value)).second) unsupported("repeated attributes");
        }
        if (tag == "Texture") texture(begin, attributes, closed);
        if (!closed) open_.push_back(tag);
    }
    void texture(std::size_t begin, const std::map<std::string, std::string>& attributes, bool closed) {
        if (!open_.empty()) invalid("nested Texture elements are unsupported");
        const auto get = [&](const char* key) -> const std::string* {
            const auto found = attributes.find(key);
            return found == attributes.end() ? nullptr : &found->second;
        };
        const auto* name_value = get("Name");
        const auto* filename_value = get("Filename");
        const auto* alternate = get("FileName");
        for (const auto* value : {name_value, filename_value, alternate})
            if (value && !ascii(*value)) unsupported("non-ASCII icon names or filenames");
        const std::string name = name_value ? *name_value : "";
        const std::string filename = filename_value ? *filename_value : alternate ? *alternate : "";
        if (filename_value && alternate && lower(*filename_value) != lower(*alternate)) invalid("a Texture has conflicting filename attributes");
        if (strip_spaces(name).empty() || strip_spaces(filename).empty()) invalid("each Texture needs a nonempty Name and Filename");
        auto definition = attributes;
        definition["Name"] = lower(name);
        definition["Filename"] = lower(filename);
        definition.erase("FileName");
        const auto previous = definitions_.find(lower(name));
        if (previous != definitions_.end() && previous->second != definition)
            invalid("duplicate icon name '" + name + "' has conflicting definitions (case-insensitive)");
        definitions_[lower(name)] = definition;
        if (!closed) invalid("Texture elements must be self-closing");
        registry_.textures.push_back({name, filename, Bytes(raw_.begin() + static_cast<std::ptrdiff_t>(begin), raw_.begin() + static_cast<std::ptrdiff_t>(at_))});
        spans_.emplace_back(begin, at_);
    }

    const Bytes& raw_;
    std::size_t at_ = 0;
    std::vector<std::string> open_;  // below the synthetic root
    std::map<std::string, std::map<std::string, std::string>> definitions_;
    std::vector<std::pair<std::size_t, std::size_t>> spans_;
    IconRegistry registry_;
};

}  // namespace

IconRegistry parse_icon_registry(const Bytes& data) { return Reader(data).parse(); }

}  // namespace cdmw::compose::detail
