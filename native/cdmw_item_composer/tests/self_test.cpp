// Native sanity checks. Parity with Python is proven by tests/test_native_overlay_merge.py.
#include "composer_internal.hpp"

#include <iostream>

using namespace cdmw::compose;

namespace {
int failures = 0;
void check(bool okay, const char* what) {
    if (!okay) {
        std::cerr << "FAILED: " << what << '\n';
        ++failures;
    }
}
Blob blob(std::string_view text) { return std::make_shared<const Bytes>(detail::bytes_of(text)); }
}  // namespace

int main() {
    for (std::size_t size : {0u, 1u, 12u, 13u, 64u, 5000u, 70000u}) {
        Bytes data(size);
        for (std::size_t i = 0; i < size; ++i) data[i] = static_cast<std::uint8_t>((i * 7) % 13 == 0 ? i : i / 3);
        const auto block = lz4::compress(data.data(), data.size());
        check(lz4::decompress(block.data(), block.size(), size) == data, "LZ4 round trip");
    }
    bool refused = false;
    try {
        const Bytes block{0x40, 'a', 'b', 'c', 'd'};
        lz4::decompress(block.data(), block.size(), 5);
    } catch (const FormatError&) {
        refused = true;
    }
    check(refused, "LZ4 size mismatch refused");

    check(detail::valid_utf8(detail::bytes_of("plain \xC3\xBC \xF0\x9F\x99\x82")), "valid UTF-8");
    for (const auto* bad : {"\xC0\xAF", "\xED\xA0\x80", "\xF4\x90\x80\x80", "\xE2\x82"})
        check(!detail::valid_utf8(detail::bytes_of(bad)), "invalid UTF-8 refused");
    check(detail::decimal_le(Bytes(12, 0xFF)) == "79228162514264337593543950335", "wide key as decimal");

    FileMap before, after, current;
    before.set("a.bin", nullptr);
    after.set("a.bin", blob("new"));
    current.set("a.bin", nullptr);
    current.set("b.bin", blob("kept"));
    const auto merged = merge_overlay_files(before, after, current);
    check(merged.items().size() == 2 && *merged.get("a.bin") == detail::bytes_of("new"), "an owned file is added");
    current.set("a.bin", blob("other"));
    bool conflict = false;
    try {
        merge_overlay_files(before, after, current);
    } catch (const OverlayConflict&) {
        conflict = true;
    }
    check(conflict, "two installs writing one file conflict");

    if (failures) return 1;
    std::cout << "composer self-test passed\n";
    return 0;
}
