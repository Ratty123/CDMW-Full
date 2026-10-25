// Test driver: runs the native merge on a serialized request so pytest can compare it with
// overlay_merge.py byte for byte. Not shipped.
//
//   cdmw_compose_cli merge <request> <response>
//   cdmw_compose_cli lz4-compress <input> <output>
//   cdmw_compose_cli lz4-decompress <input> <output> <size>
//
// Request:  "CDMWMRG1", then before, after and current, each: u32 count, then per file
//           u32 path length, UTF-8 path, u8 present, [u64 size, bytes].
// Response: "CDMWRES1", u8 status (0 ok, 1 conflict, 2 format error, 3 unsupported,
//           4 internal error), u32 message length, message, then on success the result
//           files in order, encoded like a request map.
#include "cdmw_composer/composer.hpp"

#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>

using namespace cdmw::compose;

namespace {

Bytes read_file(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error(std::string("cannot read ") + path);
    return Bytes(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

void write_file(const char* path, const Bytes& data) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (!out) throw std::runtime_error(std::string("cannot write ") + path);
}

class Cursor {
public:
    explicit Cursor(const Bytes& data) : data_(data) {}
    std::uint64_t number(std::size_t width) {
        need(width);
        std::uint64_t value = 0;
        for (std::size_t i = 0; i < width; ++i) value |= std::uint64_t(data_[at_ + i]) << (8 * i);
        at_ += width;
        return value;
    }
    Bytes take(std::uint64_t size) {
        need(size);
        Bytes out(data_.begin() + static_cast<std::ptrdiff_t>(at_), data_.begin() + static_cast<std::ptrdiff_t>(at_ + size));
        at_ += static_cast<std::size_t>(size);
        return out;
    }
    bool done() const { return at_ == data_.size(); }

private:
    void need(std::uint64_t size) const {
        if (size > data_.size() - at_) throw std::runtime_error("truncated request");
    }
    const Bytes& data_;
    std::size_t at_ = 0;
};

FileMap read_map(Cursor& in) {
    FileMap files;
    const auto count = in.number(4);
    for (std::uint64_t i = 0; i < count; ++i) {
        const auto path = in.take(in.number(4));
        Blob value;
        if (in.number(1)) value = std::make_shared<const Bytes>(in.take(in.number(8)));
        files.set(std::string(path.begin(), path.end()), value);
    }
    return files;
}

void put(Bytes& out, std::uint64_t value, std::size_t width) {
    for (std::size_t i = 0; i < width; ++i) out.push_back(static_cast<std::uint8_t>(value >> (8 * i)));
}

Bytes response(std::uint8_t status, const std::string& message, const FileMap* files) {
    Bytes out{'C', 'D', 'M', 'W', 'R', 'E', 'S', '1', status};
    put(out, message.size(), 4);
    out.insert(out.end(), message.begin(), message.end());
    if (files) {
        put(out, files->items().size(), 4);
        for (const auto& [path, value] : files->items()) {
            put(out, path.size(), 4);
            out.insert(out.end(), path.begin(), path.end());
            put(out, value ? 1 : 0, 1);
            if (value) {
                put(out, value->size(), 8);
                out.insert(out.end(), value->begin(), value->end());
            }
        }
    }
    return out;
}

Bytes merge(const Bytes& request) {
    Cursor in(request);
    if (in.take(8) != Bytes{'C', 'D', 'M', 'W', 'M', 'R', 'G', '1'}) throw std::runtime_error("not a merge request");
    const auto before = read_map(in), after = read_map(in), current = read_map(in);
    if (!in.done()) throw std::runtime_error("trailing request bytes");
    try {
        const auto result = merge_overlay_files(before, after, current);
        return response(0, "", &result);
    } catch (const OverlayConflict& error) {
        return response(1, error.what(), nullptr);
    } catch (const FormatError& error) {
        return response(2, error.what(), nullptr);
    } catch (const Unsupported& error) {
        return response(3, error.what(), nullptr);
    } catch (const std::exception& error) {
        return response(4, error.what(), nullptr);
    }
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string command = argc > 1 ? argv[1] : "";
        if (command == "merge" && argc == 4) {
            write_file(argv[3], merge(read_file(argv[2])));
        } else if (command == "lz4-compress" && argc == 4) {
            const auto input = read_file(argv[2]);
            write_file(argv[3], lz4::compress(input.data(), input.size()));
        } else if (command == "lz4-decompress" && argc == 5) {
            const auto input = read_file(argv[2]);
            try {
                write_file(argv[3], lz4::decompress(input.data(), input.size(), std::stoull(argv[4])));
            } catch (const FormatError& error) {
                std::cerr << error.what() << '\n';
                return 3;
            }
        } else {
            std::cerr << "usage: cdmw_compose_cli merge <request> <response> | lz4-compress <in> <out> | lz4-decompress <in> <out> <size>\n";
            return 2;
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
