#pragma once

#include <algorithm>
#include <array>
#include <cerrno>
#include <cctype>
#include <charconv>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <numeric>
#include <set>
#include <shared_mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <vector>

#include "mikktspace.h"
#include "xatlas.h"

#include "mesh_core.hpp"

// `out << std::setprecision(17) << value` with no float flags set is printf's
// "%.17g" text, and std::to_chars(general, 17) is specified to write exactly that
// for a finite value. It skips the locale-aware stream path, which dominated large
// OBJ and manifest exports on MSVC. Any other stream state, and non-finite values,
// keep the stream's own formatting.
inline void write_g17(std::ostream& out, double value) {
    // Callers replaced `out << std::setprecision(17) << value`, which leaves the
    // precision set for whatever the stream writes next.
    out.precision(17);
    constexpr auto stream_formatting =
        std::ios::floatfield | std::ios::showpos | std::ios::showpoint | std::ios::uppercase;
    if (!std::isfinite(value) || (out.flags() & stream_formatting) != 0 || out.width() != 0) {
        out << std::setprecision(17) << value;
        return;
    }
    char buffer[32];
    const auto result = std::to_chars(buffer, buffer + sizeof(buffer), value, std::chars_format::general, 17);
    out.write(buffer, result.ptr - buffer);
}

// The decimal text `out << value` writes for an int under the same conditions.
inline void write_int(std::ostream& out, int value) {
    const auto base = out.flags() & std::ios::basefield;
    if ((base != std::ios::dec && base != 0) || (out.flags() & std::ios::showpos) != 0 || out.width() != 0) {
        out << value;
        return;
    }
    char buffer[16];
    const auto result = std::to_chars(buffer, buffer + sizeof(buffer), value);
    out.write(buffer, result.ptr - buffer);
}

// One OBJ face corner: "v/t/n", "v/t" (normal < 0) or "v//n" (uv < 0). OBJ
// indices are one-based, so a negative index only ever marks a missing channel.
inline void write_obj_face_corner(std::ostream& out, int vertex, int uv, int normal) {
    write_int(out, vertex);
    if (uv >= 0) {
        out << '/';
        write_int(out, uv);
        if (normal >= 0) {
            out << '/';
            write_int(out, normal);
        }
    } else if (normal >= 0) {
        out << "//";
        write_int(out, normal);
    }
}
