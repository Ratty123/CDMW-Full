// Test driver: runs the native merge on a serialized request so pytest can compare it with
// overlay_merge.py byte for byte. Not shipped.
//
//   cdmw_compose_cli merge <request> <response>
//   cdmw_compose_cli overlay <request> <response>
//   cdmw_compose_cli papgt-add <papgt> <response> <name> <checksum> <flags> <first 0|1>
//   cdmw_compose_cli papgt-roundtrip <papgt> <response>
//   cdmw_compose_cli checksum <input> <output>
//   cdmw_compose_cli lz4-compress <input> <output>
//   cdmw_compose_cli lz4-decompress <input> <output> <size>
//   cdmw_compose_cli store <input> <response> <flags> <basename>
//   cdmw_compose_cli text-check <input>                       prints 1 or 0
//   cdmw_compose_cli pamt <pamt> <response>
//   cdmw_compose_cli read-archives <root> <papgt> <response> <path>...
//   cdmw_compose_cli sha256 <input>                           prints the hex digest
//   cdmw_compose_cli inflate <input> <output> <limit>
//   cdmw_compose_cli zip <archive> <response>
//
// Merge request:   "CDMWMRG1", then before, after and current, each: u32 count, then per
//                  file u32 path length, UTF-8 path, u8 present, [u64 size, bytes].
// Overlay request: "CDMWOVL1", u32 count, then per file u32 path length, path, u64 size,
//                  payload, u64 orig_size, u64 flags.
// Response:        "CDMWRES1", u8 status (0 ok, 1 conflict, 2 format error, 3 unsupported,
//                  4 internal error), u32 message length, message, then on success:
//                  merge: the result files in order, encoded like a request map;
//                  overlay: u64 + PAMT, u64 + PAZ, u32 PAMT checksum, u32 count, then per
//                  entry u32 + path, u64 offset, u64 stored size, u64 orig size;
//                  papgt: u64 + bytes.
// checksum writes u32 calculate_pa_checksum and u32 hashlittle(data, 0xC5EDE).
// store answers like papgt. pamt answers u32 count, then per entry u32 + path, u64 offset,
// u64 stored size, u64 orig size, u32 flags, u32 PAZ index. read-archives answers u32
// count, then per path u8 status (0 found, 1 absent, 2 format error, 3 unsupported),
// u32 + message, and when found u32 + PAMT path, u32 flags, u64 + decoded bytes.
// zip answers u32 count, then per member u32 + name, u32 + original name, u32 flags,
// u32 method, u32 CRC, u64 compressed size, u64 size, u32 external attributes, u64 header
// offset, then u8 read status (0 ok, 2 format error, 3 unsupported), u32 + message and
// u64 + bytes.
#include "cdmw_composer/composer.hpp"
#include "composer_internal.hpp"

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

template <class Action>
Bytes answer(Action action) {
    try {
        return action();
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

void put_bytes(Bytes& out, const Bytes& data, std::size_t width) {
    put(out, data.size(), width);
    out.insert(out.end(), data.begin(), data.end());
}

Bytes merge(const Bytes& request) {
    Cursor in(request);
    if (in.take(8) != Bytes{'C', 'D', 'M', 'W', 'M', 'R', 'G', '1'}) throw std::runtime_error("not a merge request");
    const auto before = read_map(in), after = read_map(in), current = read_map(in);
    if (!in.done()) throw std::runtime_error("trailing request bytes");
    return answer([&] {
        const auto result = merge_overlay_files(before, after, current);
        return response(0, "", &result);
    });
}

Bytes overlay(const Bytes& request) {
    Cursor in(request);
    if (in.take(8) != Bytes{'C', 'D', 'M', 'W', 'O', 'V', 'L', '1'}) throw std::runtime_error("not an overlay request");
    std::vector<OverlayFile> files(in.number(4));
    for (auto& file : files) {
        const auto path = in.take(in.number(4));
        file.path.assign(path.begin(), path.end());
        file.payload = in.take(in.number(8));
        file.orig_size = in.number(8);
        file.flags = in.number(8);
    }
    if (!in.done()) throw std::runtime_error("trailing request bytes");
    return answer([&] {
        const auto archive = build_overlay_archive(files);
        auto out = response(0, "", nullptr);
        put_bytes(out, archive.pamt, 8);
        put_bytes(out, archive.paz, 8);
        put(out, archive.pamt_checksum, 4);
        put(out, archive.entries.size(), 4);
        for (const auto& entry : archive.entries) {
            put_bytes(out, Bytes(entry.path.begin(), entry.path.end()), 4);
            put(out, entry.offset, 8);
            put(out, entry.stored_size, 8);
            put(out, entry.orig_size, 8);
        }
        return out;
    });
}

Bytes bytes_response(const Bytes& data) {
    auto out = response(0, "", nullptr);
    put_bytes(out, data, 8);
    return out;
}

Bytes text(const std::string& value) { return Bytes(value.begin(), value.end()); }

Bytes pamt_listing(const Bytes& data, const char* path) {
    return answer([&] {
        const auto entries = parse_pamt(data, detail::path_of(path));
        auto out = response(0, "", nullptr);
        put(out, entries.size(), 4);
        for (const auto& entry : entries) {
            put_bytes(out, text(entry.path), 4);
            put(out, entry.offset, 8);
            put(out, entry.stored_size, 8);
            put(out, entry.orig_size, 8);
            put(out, entry.flags, 4);
            put(out, entry.paz_index, 4);
        }
        return out;
    });
}

Bytes zip_listing(const Bytes& data) {
    return answer([&] {
        const ZipArchive archive(data);
        auto out = response(0, "", nullptr);
        put(out, archive.members().size(), 4);
        for (const auto& member : archive.members()) {
            put_bytes(out, text(member.name), 4);
            put_bytes(out, text(member.orig_name), 4);
            put(out, member.flags, 4);
            put(out, member.method, 4);
            put(out, member.crc, 4);
            put(out, member.compressed_size, 8);
            put(out, member.size, 8);
            put(out, member.external_attr, 4);
            put(out, member.header_offset, 8);
            std::uint8_t status = 0;
            std::string message;
            Bytes bytes;
            try {
                bytes = archive.read(member);
            } catch (const FormatError& error) {
                status = 2;
                message = error.what();
            } catch (const Unsupported& error) {
                status = 3;
                message = error.what();
            }
            out.push_back(status);
            put_bytes(out, text(message), 4);
            put_bytes(out, bytes, 8);
        }
        return out;
    });
}

Bytes read_archives(const char* root, const Bytes& papgt, int count, char** paths) {
    return answer([&] {
        const MountedArchives archives(detail::path_of(root), papgt);
        auto out = response(0, "", nullptr);
        put(out, static_cast<std::uint64_t>(count), 4);
        for (int i = 0; i < count; ++i) {
            const auto* entry = archives.find(paths[i]);
            std::uint8_t status = entry ? 0 : 1;
            std::string message;
            Bytes data;
            if (entry) {
                try {
                    data = read_entry(*entry);
                } catch (const FormatError& error) {
                    status = 2;
                    message = error.what();
                } catch (const Unsupported& error) {
                    status = 3;
                    message = error.what();
                }
            }
            out.push_back(status);
            put_bytes(out, text(message), 4);
            if (status == 0) {
                put_bytes(out, text(detail::utf8_of(entry->pamt_path)), 4);
                put(out, entry->flags, 4);
                put_bytes(out, data, 8);
            }
        }
        return out;
    });
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string command = argc > 1 ? argv[1] : "";
        if (command == "merge" && argc == 4) {
            write_file(argv[3], merge(read_file(argv[2])));
        } else if (command == "overlay" && argc == 4) {
            write_file(argv[3], overlay(read_file(argv[2])));
        } else if (command == "papgt-add" && argc == 8) {
            const auto data = read_file(argv[2]);
            const std::string name = argv[4], first = argv[7];
            const auto checksum = static_cast<std::uint32_t>(std::stoul(argv[5])), flags = static_cast<std::uint32_t>(std::stoul(argv[6]));
            write_file(argv[3], answer([&] { return bytes_response(papgt_with_directory(data, name, checksum, flags, first == "1")); }));
        } else if (command == "papgt-roundtrip" && argc == 4) {
            const auto data = read_file(argv[2]);
            write_file(argv[3], answer([&] { return bytes_response(serialize_papgt(parse_papgt(data), Bytes(data.begin(), data.begin() + std::min<std::size_t>(12, data.size())))); }));
        } else if (command == "checksum" && argc == 4) {
            const auto data = read_file(argv[2]);
            Bytes out;
            put(out, pa_checksum(data.data(), data.size()), 4);
            put(out, hashlittle(data.data(), data.size(), 0xC5EDE), 4);
            write_file(argv[3], out);
        } else if (command == "store" && argc == 6) {
            const auto data = read_file(argv[2]);
            const auto flags = std::stoull(argv[4]);
            write_file(argv[3], answer([&] { return bytes_response(stored_payload(data, flags, argv[5])); }));
        } else if (command == "text-check" && argc == 3) {
            std::cout << (detail::text_like(read_file(argv[2])) ? 1 : 0) << '\n';
        } else if (command == "pamt" && argc == 4) {
            write_file(argv[3], pamt_listing(read_file(argv[2]), argv[2]));
        } else if (command == "read-archives" && argc >= 5) {
            write_file(argv[4], read_archives(argv[2], read_file(argv[3]), argc - 5, argv + 5));
        } else if (command == "sha256" && argc == 3) {
            std::cout << sha256_hex(read_file(argv[2])) << '\n';
        } else if (command == "inflate" && argc == 5) {
            const auto input = read_file(argv[2]);
            try {
                write_file(argv[3], inflate(input.data(), input.size(), std::stoull(argv[4])));
            } catch (const FormatError& error) {
                std::cerr << error.what() << '\n';
                return 3;
            }
        } else if (command == "zip" && argc == 4) {
            write_file(argv[3], zip_listing(read_file(argv[2])));
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
