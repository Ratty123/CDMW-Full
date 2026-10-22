#include <array>
#include <cmath>
#include <iostream>
#include <map>
#include <stdexcept>
#include <utility>
#include <vector>

namespace cdmw_mesh_core {
using Vec3 = std::array<double, 3>;
std::vector<Vec3> mesh_editor_smooth_refit_contact(
    const std::vector<Vec3>&, const std::vector<double>&,
    const std::map<std::pair<std::size_t, std::size_t>, double>&, double, int);
}

int main() {
    using namespace cdmw_mesh_core;
    try {
        // Uneven cloth sampling, a tiny exclusion draw and an unused record
        // share the solve. Each disconnected component has uniform motion.
        std::vector<Vec3> target(516, Vec3{.03, -.004, .01});
        std::vector<double> mass(target.size());
        std::map<std::pair<std::size_t, std::size_t>, double> edges;
        for (std::size_t i = 0; i < 512; ++i) {
            mass[i] = 1.0e-11 * std::pow(10.0, static_cast<double>(i % 7));
            if (i > 0) edges[{i - 1, i}] = .1 + static_cast<double>(i % 13);
        }
        for (std::size_t i = 512; i < 515; ++i) {
            mass[i] = 1.0e-11;
            target[i] = {-.02, .01, .004};
        }
        edges[{512, 513}] = edges[{513, 514}] = edges[{512, 514}] = 1.0;
        target[515] = {};
        const auto translated = mesh_editor_smooth_refit_contact(target, mass, edges, .005, 256);
        for (std::size_t i = 0; i < target.size(); ++i)
            for (int axis = 0; axis < 3; ++axis)
                if (std::abs(translated[i][axis] - target[i][axis]) > 1.0e-12)
                    throw std::runtime_error("screened contact changed a uniform component translation");

        // Exact solution of a three-node screened Laplacian. Nonuniform
        // requests must still diffuse, with the constant axis preserved.
        target = {{1., 3., 0.}, {0., 3., 0.}, {0., 3., -2.}};
        mass = {1., 1., 1.};
        edges = {{{0, 1}, 1.}, {{1, 2}, 1.}};
        const std::vector<Vec3> expected{{.625, 3., -.25}, {.25, 3., -.5}, {.125, 3., -1.25}};
        const auto smoothed = mesh_editor_smooth_refit_contact(target, mass, edges, 1., 256);
        for (std::size_t i = 0; i < expected.size(); ++i)
            for (int axis = 0; axis < 3; ++axis)
                if (std::abs(smoothed[i][axis] - expected[i][axis]) > 1.0e-10)
                    throw std::runtime_error("screened contact did not satisfy the known solution");
        bool rejected = false;
        try {
            mesh_editor_smooth_refit_contact(target, mass, edges, 1., 0);
        } catch (const std::runtime_error&) {
            rejected = true;
        }
        if (!rejected) throw std::runtime_error("an unfinished contact solve was accepted");
        std::cout << "Refit contact solver checks passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
