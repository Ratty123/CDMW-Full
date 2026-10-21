#include "paired_item_publication.hpp"
#include <iostream>
#include <stdexcept>

namespace {
namespace r = cditem::research;
using Unit = r::PairedPublication;
unsigned checks{}, cases{}, observations{}, early_visibility{}, partial_pair_visibility{};
void require(bool condition, const char* message) {
    ++checks;
    if (!condition) throw std::runtime_error(message);
}

std::array<r::Request, 2> requests() {
    std::array<r::Request, 2> result{};
    for (std::size_t i = 0; i < result.size(); ++i) {
        auto& item = result[i];
        item.identity.package[0] = static_cast<std::uint8_t>(i + 1);
        item.identity.numeric_key = static_cast<std::uint32_t>(1001 + i * 3);
        item.identity.name_key = static_cast<std::uint32_t>(2001 + i * 3);
        item.identity.donor = 77;
        item.identity.ordinal = static_cast<std::uint16_t>(r::stock_count + i);
        auto& resource = item.resource;
        constexpr char archive[] = "owned-fixture/private-a/0.paz";
        std::memcpy(resource.expected_archive.data(), archive, sizeof archive);
        resource.expected_archive[22] = static_cast<char>('a' + i);
        resource.selected_archive = resource.expected_archive;
        resource.archive_size = 112;
        resource.payload_size = resource.requested = resource.completed_size = 102;
        resource.state = r::IoState::complete;
        for (std::uint32_t n = 0; n < resource.payload_size; ++n) {
            const auto byte = static_cast<std::uint8_t>(n + 31 * i);
            resource.archive[n] = resource.expected[n] = resource.completed[n] = byte;
        }
    }
    return result;
}

struct MapImage {
    r::Map header;
    std::array<r::Bucket, r::bucket_count> buckets;
    std::array<r::Node*, r::capacity> entries;
    explicit MapImage(const r::Map& map) : header(map) {
        std::memcpy(buckets.data(), reinterpret_cast<const void*>(map.bucket_data), sizeof buckets);
        std::memcpy(entries.data(), reinterpret_cast<const void*>(map.entries), sizeof entries);
    }
    bool same(const r::Map& map) const {
        return std::memcmp(&header, &map, sizeof header) == 0
            && std::memcmp(buckets.data(), reinterpret_cast<const void*>(map.bucket_data), sizeof buckets) == 0
            && std::memcmp(entries.data(), reinterpret_cast<const void*>(map.entries), sizeof entries) == 0;
    }
};

struct Probe {
    Unit* unit;
    r::AllocationStats* allocations;
    std::array<r::Request, 2> expected;
    unsigned allocation_attempts{}, errors{}, calls{};
    bool nested{};
    std::array<Unit::Write, 32> writes{};
};

void observe(void* opaque, const Unit& unit, Unit::MapKind, Unit::Write write) noexcept {
    auto& probe = *static_cast<Probe*>(opaque);
    auto check = [&](bool valid) noexcept { ++checks; if (!valid) ++probe.errors; };
    check(probe.calls < probe.writes.size());
    if (probe.calls < probe.writes.size()) probe.writes[probe.calls] = write;
    ++probe.calls; ++observations;
    check(unit.state() == Unit::State::publishing);
    check(probe.allocations->attempts == probe.allocation_attempts);
    check(probe.allocations->destroyed == 0);
    check(unit.joined_backing_valid());
    for (std::uint32_t i = 0; i < r::stock_count; ++i) {
        std::uint32_t value = 999;
        check(unit.numeric(10 + i, value) && value == i);
        check(unit.name(20 + i, value) && value == i);
    }
    for (const auto& item : probe.expected) {
        std::uint32_t numeric = 999, name = 999;
        const bool number_visible = unit.numeric(item.identity.numeric_key, numeric);
        const bool name_visible = unit.name(item.identity.name_key, name);
        if (number_visible != name_visible) ++partial_pair_visibility;
        if (number_visible || name_visible) {
            check(!number_visible || numeric == item.identity.ordinal);
            check(!name_visible || name == item.identity.ordinal);
            const auto* row = unit.resolve(item.identity.ordinal);
            check(row && row->identity == item.identity);
            if (row && row->resource) {
                check(row->resource->valid());
                check(row->resource->selected_archive == item.resource.expected_archive);
                check(std::memcmp(row->resource->completed.data(), item.resource.expected.data(), 102) == 0);
            } else check(false);
            if (unit.owner_count() == r::stock_count) ++early_visibility;
        }
    }
    if (probe.nested) {
        const auto state = unit.state();
        check(!probe.unit->publish());
        check(!probe.unit->prepare(probe.expected));
        check(!probe.unit->corrupt_map(Unit::MapKind::name));
        check(!probe.unit->corrupt_backing(Unit::Corruption::row));
        check(unit.state() == state && probe.allocations->destroyed == 0);
    }
}

void assert_absent(const Unit& unit, const std::array<r::Request, 2>& input) {
    for (const auto& item : input) {
        std::uint32_t value{};
        require(!unit.numeric(item.identity.numeric_key, value), "refusal exposes no numeric entry");
        require(!unit.name(item.identity.name_key, value), "refusal exposes no name entry");
        require(!unit.resolve(item.identity.ordinal), "refusal releases unpublished primary row");
    }
}

void positive(bool nested) {
    r::AllocationStats stats;
    {
        Unit unit(stats);
        auto input = requests();
        const auto expected = input;
        const MapImage original_numeric(unit.numeric_map()), original_names(unit.name_map());
        require(unit.prepare(input), "prepare both maps and concrete owned backing");
        require(original_numeric.same(unit.numeric_map()) && original_names.same(unit.name_map()),
            "preparation writes neither map");
        require(stats.allocated == 8 && !stats.destroyed, "eight new objects have a common owner");
        require(unit.joined_backing_valid(), "actual prepared cells/metadata/routes join before publication");
        require(unit.resolve(2)->resource != unit.resolve(3)->resource,
            "same-donor items retain distinct resources");
        // Preparation owns its values. A caller changing or discarding input
        // cannot change a row or payload already prepared for publication.
        input[0].resource.completed.fill(0xff);
        input[0].identity.numeric_key = 9999;
        require(!unit.prepare(input), "repeated preparation refuses without destroying first preparation");
        Probe probe{&unit, &stats, expected, stats.attempts, 0, 0, nested, {}};
        require(unit.publish(observe, &probe), "joint publication succeeds");
        require(!probe.errors && probe.calls == 17, "every store observation sees valid joined ownership");
        require(unit.state() == Unit::State::published && unit.owner_count() == 4, "final owner state");
        require(unit.numeric_map().count == 4 && unit.name_map().count == 4, "both maps complete");
        require(unit.numeric_map().entries == original_numeric.header.entries
            && unit.name_map().entries == original_names.header.entries, "entry backing does not move");
        require(unit.numeric_map().bucket_data == original_numeric.header.bucket_data
            && unit.name_map().bucket_data == original_names.header.bucket_data, "bucket backing does not move");
        require(!unit.publish() && stats.destroyed == 0, "repeat publication leaves published ownership intact");
        require(!unit.corrupt_backing(Unit::Corruption::row), "published backing has no mutable API");
    }
    require(stats.destroyed == stats.allocated && stats.allocated == 8, "unit destruction reclaims each object once");
    ++cases;
}

void allocation_refusals() {
    for (unsigned fail = 1; fail <= 8; ++fail) {
        r::AllocationStats stats; stats.fail_at = fail;
        {
            Unit unit(stats); const auto input = requests();
            const MapImage numeric(unit.numeric_map()), names(unit.name_map());
            require(!unit.prepare(input) && unit.error() == Unit::Error::allocation,
                "each allocation failure refuses");
            require(numeric.same(unit.numeric_map()) && names.same(unit.name_map()),
                "allocation failure changes neither map");
            assert_absent(unit, input);
            require(stats.destroyed == stats.allocated && stats.allocated == fail - 1,
                "allocation failure reclaims only successfully allocated objects");
        }
        require(stats.destroyed == stats.allocated, "destruction does not double free refused preparation");
        ++cases;
    }
}

void stale_maps() {
    for (const auto kind : {Unit::MapKind::numeric, Unit::MapKind::name}) {
        r::AllocationStats stats;
        Unit unit(stats); const auto input = requests();
        require(unit.prepare(input), "stale case first prepares");
        require(unit.corrupt_map(kind), "inject a source map change");
        const MapImage numeric(unit.numeric_map()), names(unit.name_map());
        require(!unit.publish() && unit.error() == Unit::Error::changed, "both maps revalidate before first store");
        require(numeric.same(unit.numeric_map()) && names.same(unit.name_map()), "stale second map cannot publish first map");
        assert_absent(unit, input);
        require(stats.destroyed == stats.allocated, "stale preparation releases every new owned object");
        ++cases;
    }
}

void backing_refusals() {
    for (const auto part : {Unit::Corruption::row, Unit::Corruption::metadata, Unit::Corruption::primary,
            Unit::Corruption::expiry, Unit::Corruption::route, Unit::Corruption::pending,
            Unit::Corruption::short_read, Unit::Corruption::payload}) {
        r::AllocationStats stats;
        Unit unit(stats); const auto input = requests();
        require(unit.prepare(input) && unit.corrupt_backing(part), "inject one prepared backing drift");
        const MapImage numeric(unit.numeric_map()), names(unit.name_map());
        require(!unit.publish() && unit.error() == Unit::Error::backing, "drifted backing refuses");
        require(numeric.same(unit.numeric_map()) && names.same(unit.name_map()), "backing drift refuses before either map write");
        assert_absent(unit, input);
        require(stats.destroyed == stats.allocated, "backing refusal reclaims every new object once");
        ++cases;
    }
}

void input_refusals() {
    for (unsigned mode = 0; mode < 19; ++mode) {
        r::AllocationStats stats;
        Unit unit(stats); auto input = requests();
        switch (mode) {
        case 0: input[0].resource.state = r::IoState::pending; break;
        case 1: input[0].resource.state = r::IoState::failed; break;
        case 2: --input[0].resource.completed_size; break;
        case 3: input[0].resource.completed[0] ^= 1; break;
        case 4: input[0].resource.selected_archive[0] = 'x'; break;
        case 5: input[0].resource.offset = std::numeric_limits<std::uint32_t>::max(); break;
        case 6: input[0].resource.requested = 112; break;
        case 7: input[1].identity.name_key = 20; break;
        case 8: input[1].identity.name_key = input[0].identity.name_key; break;
        case 9: input[1].identity.ordinal = 0xffff; break;
        case 10: input[0].resource.archive[0] ^= 1; break;
        case 11: input[0].identity.package.fill(0); break;
        case 12: input[0].identity.numeric_key = 0; break;
        case 13: input[0].identity.name_key = 0; break;
        case 14: input[1].identity.numeric_key = input[0].identity.numeric_key; break;
        case 15: input[1].identity.numeric_key = 10; break;
        case 16: input[0].resource.archive_size = r::payload_capacity + 1; break;
        case 17: input[0].resource.payload_size = 0; break;
        case 18: input[0].resource.payload_size = r::payload_capacity + 1; break;
        }
        const MapImage numeric(unit.numeric_map()), names(unit.name_map());
        require(!unit.prepare(input), "invalid identity/resource or second-map collision refuses");
        require(numeric.same(unit.numeric_map()) && names.same(unit.name_map()), "invalid input changes neither map");
        require(stats.destroyed == stats.allocated, "invalid input cleanup complete");
        require(!unit.publish(), "refused preparation cannot publish");
        ++cases;
    }
}

void count_refusals() {
    for (const bool empty : {true, false}) {
        r::AllocationStats stats;
        Unit unit(stats);
        const std::array<r::Request, r::max_new + 1> oversized{};
        const MapImage numeric(unit.numeric_map()), names(unit.name_map());
        const auto input = empty ? std::span<const r::Request>{} : std::span<const r::Request>{oversized};
        require(!unit.prepare(input) && unit.error() == Unit::Error::request,
            "empty or excessive request count refuses before allocation");
        require(numeric.same(unit.numeric_map()) && names.same(unit.name_map()),
            "request count refusal changes neither map");
        require(!stats.attempts, "request count is bounded before allocation");
        ++cases;
    }
}
} // namespace

int main() {
    try {
        positive(false); positive(true);
        allocation_refusals(); stale_maps(); backing_refusals(); input_refusals(); count_refusals();
        require(early_visibility > 0, "visible ordinals resolve before the final owner count");
        require(partial_pair_visibility > 0, "two maps are not atomically published to arbitrary readers");
        std::cout << "{\"status\":\"owned_paired_publication_passed\",\"cases\":" << cases
            << ",\"checks\":" << checks << ",\"write_observations\":" << observations
            << ",\"early_visible_backing_observations\":" << early_visibility
            << ",\"partial_pair_observations\":" << partial_pair_visibility
            << ",\"native_io_executed\":false,\"native_constructor_executed\":false"
               ",\"native_lookup_executed\":false,\"concurrent_readers_qualified\":false"
               ",\"game_used\":false,\"native_admission\":false}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
