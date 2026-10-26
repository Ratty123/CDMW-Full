#include "composer_internal.hpp"

#include <atomic>
#include <system_error>
#include <thread>

namespace cdmw::compose {

Blob FileMap::get(const std::string& path) const {
    const auto found = index_.find(path);
    return found == index_.end() ? nullptr : items_[found->second].second;
}

bool FileMap::contains(const std::string& path) const { return index_.count(path) != 0; }

void FileMap::set(const std::string& path, Blob value) {
    const auto found = index_.find(path);
    if (found != index_.end()) {
        items_[found->second].second = std::move(value);
        return;
    }
    index_.emplace(path, items_.size());
    items_.emplace_back(path, std::move(value));
}

}  // namespace cdmw::compose

namespace cdmw::compose::detail {

bool valid_utf8(const std::uint8_t* data, std::size_t size) {
    std::size_t at = 0;
    const auto continuation = [&](std::size_t offset, std::uint8_t low = 0x80, std::uint8_t high = 0xBF) {
        return at + offset < size && data[at + offset] >= low && data[at + offset] <= high;
    };
    while (at < size) {
        const auto lead = data[at];
        if (lead < 0x80) {
            at += 1;
        } else if (lead >= 0xC2 && lead <= 0xDF) {
            if (!continuation(1)) return false;
            at += 2;
        } else if (lead >= 0xE0 && lead <= 0xEF) {
            const std::uint8_t low = lead == 0xE0 ? 0xA0 : 0x80, high = lead == 0xED ? 0x9F : 0xBF;
            if (!continuation(1, low, high) || !continuation(2)) return false;
            at += 3;
        } else if (lead >= 0xF0 && lead <= 0xF4) {
            const std::uint8_t low = lead == 0xF0 ? 0x90 : 0x80, high = lead == 0xF4 ? 0x8F : 0xBF;
            if (!continuation(1, low, high) || !continuation(2) || !continuation(3)) return false;
            at += 4;
        } else {
            return false;
        }
    }
    return true;
}

std::string decimal_le(const Bytes& data) {
    std::vector<std::uint32_t> digits{0};  // base 1e9, least significant first
    for (auto it = data.rbegin(); it != data.rend(); ++it) {
        std::uint64_t carry = *it;
        for (auto& digit : digits) {
            const auto value = static_cast<std::uint64_t>(digit) * 256 + carry;
            digit = static_cast<std::uint32_t>(value % 1000000000u);
            carry = value / 1000000000u;
        }
        while (carry) {
            digits.push_back(static_cast<std::uint32_t>(carry % 1000000000u));
            carry /= 1000000000u;
        }
    }
    std::string text = std::to_string(digits.back());
    for (auto it = digits.rbegin() + 1; it != digits.rend(); ++it) {
        const auto part = std::to_string(*it);
        text += std::string(9 - part.size(), '0') + part;
    }
    return text;
}

std::string python_bytes_repr(const Bytes& data) {
    const char* hex = "0123456789abcdef";
    const bool double_quote = std::find(data.begin(), data.end(), '\'') != data.end() &&
                              std::find(data.begin(), data.end(), '"') == data.end();
    std::string text = double_quote ? "b\"" : "b'";
    for (const auto byte : data) {
        if (byte == '\\') text += "\\\\";
        else if (byte == '\'' && !double_quote) text += "\\'";
        else if (byte == '\t') text += "\\t";
        else if (byte == '\n') text += "\\n";
        else if (byte == '\r') text += "\\r";
        else if (byte < 0x20 || byte >= 0x7F) text += std::string("\\x") + hex[byte >> 4] + hex[byte & 15];
        else text += static_cast<char>(byte);
    }
    return text + (double_quote ? "\"" : "'");
}

std::string replace_all(std::string text, std::string_view from, std::string_view to) {
    if (from.empty()) return text;
    for (std::size_t at = 0; (at = text.find(from, at)) != std::string::npos; at += to.size()) text.replace(at, from.size(), to);
    return text;
}

void parallel_for(std::size_t count, const std::function<void(std::size_t)>& work) {
    std::atomic<std::size_t> next{0};
    const auto run = [&] {
        for (std::size_t index; (index = next.fetch_add(1)) < count;) work(index);
    };
    const std::size_t workers = std::min<std::size_t>(count, std::clamp<std::size_t>(std::thread::hardware_concurrency(), 1, 8));
    std::vector<std::thread> threads;
    for (std::size_t i = 1; i < workers; ++i) {
        try {
            threads.emplace_back(run);
        } catch (const std::system_error&) {
            break;  // the threads already started and this one finish the work
        }
    }
    run();
    for (auto& thread : threads) thread.join();
}

}  // namespace cdmw::compose::detail
