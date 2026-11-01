// bone_offset_table.parse_bone_offset_table: the prefab entries of
// character/descriptors/boneoffset/boneoffsetsample.xml.
//
// The file closes elements with `</>`. This reader accepts exactly the subset the Python
// reader accepts (elements, quoted attributes, comments, character data) and fails in the
// same places, always with OverlayConflict, as overlay_merge._bone_offsets reports them.
#include "composer_internal.hpp"

#include <tuple>

namespace cdmw::compose::detail {
namespace {

[[noreturn]] void fail(const std::string& reason) { throw OverlayConflict("Unsupported bone offset table: " + reason + "."); }

bool space(std::uint8_t c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
bool name_start(std::uint8_t c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == ':'; }
bool name_char(std::uint8_t c) { return name_start(c) || (c >= '0' && c <= '9') || c == '.' || c == '-'; }
// bytes.strip() whitespace
bool python_space(std::uint8_t c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == 0x0B || c == 0x0C; }

struct Open {
    std::string name;
    std::size_t start = 0;
    std::map<std::string, Bytes> attributes;
};

class Reader {
public:
    explicit Reader(const Bytes& raw) : raw_(raw) {}

    BoneOffsetTable parse() {
        if (raw_.size() > 4u * 1024u * 1024u) fail("larger than 4 MiB");
        at_ = starts_with(raw_, "\xEF\xBB\xBF") ? 3 : 0;
        if (!valid_utf8(raw_.data() + at_, raw_.size() - at_)) fail("not UTF-8");
        while (at_ < raw_.size()) {
            if (raw_[at_] != '<') {
                const auto found = std::find(raw_.begin() + static_cast<std::ptrdiff_t>(at_), raw_.end(), '<');
                at_ = static_cast<std::size_t>(found - raw_.begin());
            } else if (ahead(at_, "<!--")) {
                const auto found = find(at_ + 4, "-->");
                if (found == npos) fail("an unterminated comment");
                at_ = found + 3;
            } else if (ahead(at_, "<!") || ahead(at_, "<?")) {
                fail("declarations and processing instructions");
            } else if (ahead(at_, "</")) {
                end_tag();
            } else {
                start_tag();
            }
        }
        if (!stack_.empty()) fail("an unclosed element");
        if (sections_.size() != 1) fail("expected one BoneOffsetByPrefab section, found " + std::to_string(sections_.size()));
        BoneOffsetTable table;
        table.insert = sections_.front();
        for (const auto& [start, end, prefab] : entries_) {
            if (std::all_of(prefab.begin(), prefab.end(), python_space)) fail("a prefab entry without PrefabName");
            auto [line_start, line_end] = line_span(start, end);
            table.entries.push_back({lower_ascii(text_of(prefab)), line_start, line_end});
        }
        return table;
    }

private:
    static constexpr std::size_t npos = static_cast<std::size_t>(-1);

    bool ahead(std::size_t at, std::string_view text) const {
        return raw_.size() - at >= text.size() &&
               std::equal(text.begin(), text.end(), raw_.begin() + static_cast<std::ptrdiff_t>(at), [](char a, std::uint8_t b) { return same_byte(a, b); });
    }
    std::size_t find(std::size_t from, std::string_view text) const {
        if (from > raw_.size()) return npos;
        const auto found = std::search(raw_.begin() + static_cast<std::ptrdiff_t>(from), raw_.end(), text.begin(), text.end(),
                                       [](std::uint8_t a, char b) { return same_byte(b, a); });
        return found == raw_.end() ? npos : static_cast<std::size_t>(found - raw_.begin());
    }
    std::size_t name_end(std::size_t at) const {
        if (at >= raw_.size() || !name_start(raw_[at])) return npos;
        ++at;
        while (at < raw_.size() && name_char(raw_[at])) ++at;
        return at;
    }
    std::string text(std::size_t begin, std::size_t end) const {
        return std::string(raw_.begin() + static_cast<std::ptrdiff_t>(begin), raw_.begin() + static_cast<std::ptrdiff_t>(end));
    }
    static std::string lower_ascii(std::string value) {
        for (auto& c : value) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
        return value;
    }
    bool is_entry(const std::string& name) const {
        return stack_.size() == 1 && stack_.front().name == "BoneOffsetByPrefab" && name == "BoneDesc";
    }
    void entry(std::size_t start, std::size_t end, const std::map<std::string, Bytes>& attributes) {
        const auto found = attributes.find("PrefabName");
        entries_.emplace_back(start, end, found == attributes.end() ? Bytes() : found->second);
    }
    std::size_t line_head(std::size_t at) const {
        while (at > 0 && raw_[at - 1] != '\n') --at;
        return at;
    }
    bool blank(std::size_t begin, std::size_t end) const {
        for (auto at = begin; at < end; ++at)
            if (raw_[at] != ' ' && raw_[at] != '\t') return false;
        return true;
    }
    std::pair<std::size_t, std::size_t> line_span(std::size_t start, std::size_t end) const {
        const auto head = line_head(start);
        if (!blank(head, start)) return {start, end};
        auto tail = end;
        while (tail < raw_.size() && (raw_[tail] == ' ' || raw_[tail] == '\t')) ++tail;
        if (ahead(tail, "\r\n")) return {head, tail + 2};
        if (ahead(tail, "\n")) return {head, tail + 1};
        return {start, end};
    }
    void skip_space() {
        while (at_ < raw_.size() && space(raw_[at_])) ++at_;
    }
    void end_tag() {
        const auto closer = at_;
        const auto named = name_end(at_ + 2);
        at_ = named == npos ? at_ + 2 : named;
        skip_space();
        if (at_ >= raw_.size() || raw_[at_] != '>') fail("an end tag that does not close");
        if (stack_.empty()) fail("an end tag without an element");
        const auto open = std::move(stack_.back());
        stack_.pop_back();
        if (named != npos && text(closer + 2, named) != open.name) fail("mismatched end tag");
        ++at_;
        if (stack_.empty() && open.name == "BoneOffsetByPrefab") {
            const auto head = line_head(closer);
            sections_.push_back(blank(head, closer) ? head : closer);
        } else if (is_entry(open.name)) {
            entry(open.start, at_, open.attributes);
        }
    }
    void start_tag() {
        Open open;
        open.start = at_;
        const auto named = name_end(at_ + 1);
        if (named == npos) fail("a tag without a name");
        open.name = text(at_ + 1, named);
        at_ = named;
        bool closed = false;
        for (;;) {
            const auto spaced = at_;
            skip_space();
            if (at_ >= raw_.size()) fail("the file ends inside a tag");
            if (ahead(at_, "/>")) {
                at_ += 2;
                closed = true;
                break;
            }
            if (raw_[at_] == '>') {
                ++at_;
                break;
            }
            const auto key_end = name_end(at_);
            if (key_end == npos || spaced == at_) fail("a malformed attribute");
            auto key = text(at_, key_end);
            at_ = key_end;
            skip_space();
            if (at_ >= raw_.size() || raw_[at_] != '=') fail("an attribute without a value");
            ++at_;
            skip_space();
            if (at_ >= raw_.size() || (raw_[at_] != '"' && raw_[at_] != '\'')) fail("an unquoted attribute value");
            const auto quote = raw_[at_];
            const auto end = std::find(raw_.begin() + static_cast<std::ptrdiff_t>(at_ + 1), raw_.end(), quote);
            if (end == raw_.end() || std::find(raw_.begin() + static_cast<std::ptrdiff_t>(at_ + 1), end, '<') != end)
                fail("an unterminated attribute value");
            Bytes value(raw_.begin() + static_cast<std::ptrdiff_t>(at_ + 1), end);
            if (!open.attributes.emplace(std::move(key), std::move(value)).second) fail("a repeated attribute");
            at_ = static_cast<std::size_t>(end - raw_.begin()) + 1;
        }
        if (closed) {
            if (stack_.empty() && open.name == "BoneOffsetByPrefab") fail("an empty section without a closing tag");
            if (is_entry(open.name)) entry(open.start, at_, open.attributes);
        } else {
            stack_.push_back(std::move(open));
        }
    }

    const Bytes& raw_;
    std::size_t at_ = 0;
    std::vector<Open> stack_;
    std::vector<std::size_t> sections_;
    std::vector<std::tuple<std::size_t, std::size_t, Bytes>> entries_;
};

}  // namespace

BoneOffsetTable parse_bone_offset_table(const Bytes& data) { return Reader(data).parse(); }

Bytes bone_offset_frame(const Bytes& data, const BoneOffsetTable& table) {
    Bytes out;
    std::size_t cursor = 0;
    for (const auto& entry : table.entries) {
        append(out, slice(data, cursor, entry.start));
        cursor = entry.end;
    }
    append(out, slice(data, cursor, data.size()));
    return out;
}

}  // namespace cdmw::compose::detail
