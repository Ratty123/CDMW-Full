#pragma once
// Research-only owned-memory experiment. No game ABI, engine decoder, file I/O,
// constructor execution or concurrent-reader contract is implemented here.
// Map layout and store order derive from retained CDItem B61/B111; those sealed
// experiments remain unchanged. This successor validates both maps first.
#include <array>
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <span>

namespace cditem::research {
static_assert(sizeof(void*) == 8 && std::endian::native == std::endian::little);
constexpr std::size_t stock_count = 2, max_new = 4, capacity = 16;
constexpr std::size_t bucket_count = 3, payload_capacity = 128;

struct Map {
    std::uint32_t buckets{}, count{}, capacity{}, caller_counter{};
    std::uintptr_t bucket_data{}, entries{};
};
struct Pair { std::uint32_t key{}, index{}; };
struct Bucket { std::uint32_t count{}, reserved{}; std::array<Pair, 31> pairs{}; };
struct Node { std::uint32_t coordinate{}, key{}, value{}; };
static_assert(sizeof(Map) == 32 && offsetof(Map, bucket_data) == 16);
static_assert(sizeof(Bucket) == 256 && offsetof(Bucket, pairs) == 8);
static_assert(sizeof(Node) == 12 && offsetof(Node, value) == 8);

enum class IoState { pending, failed, complete };
// These are bytes owned by the fixture, not a native handle or read receipt.
struct Resource {
    std::array<char, 96> expected_archive{}, selected_archive{};
    std::array<std::uint8_t, payload_capacity> archive{}, expected{}, completed{};
    std::uint32_t archive_size{}, offset{}, payload_size{}, requested{}, completed_size{};
    IoState state{IoState::pending};
    bool valid() const noexcept {
        if (expected_archive[0] == '\0' || expected_archive.back() != '\0'
            || expected_archive != selected_archive || state != IoState::complete
            || !payload_size || archive_size > payload_capacity || offset > archive_size
            || payload_size > archive_size - offset || requested != payload_size
            || completed_size != payload_size) return false;
        return std::memcmp(expected.data(), archive.data() + offset, payload_size) == 0
            && std::memcmp(expected.data(), completed.data(), payload_size) == 0;
    }
};
struct Identity {
    std::array<std::uint8_t, 16> package{};
    std::uint32_t numeric_key{}, name_key{}, donor{};
    std::uint16_t ordinal{};
    bool operator==(const Identity&) const = default;
};
struct Request { Identity identity{}; Resource resource{}; };
struct Row { Identity identity{}; const Resource* resource{}; };
// The second word is an owned-fixture route index, not an engine metadata ABI.
struct Metadata { std::uint32_t numeric_key{}, route_index{}; };
static_assert(sizeof(Metadata) == 8);

struct AllocationStats { unsigned attempts{}, fail_at{}, allocated{}, destroyed{}; };
template<class T> struct Tracked {
    AllocationStats* stats;
    T value;
    Tracked(AllocationStats& counts, const T& source) : stats(&counts), value(source) {
        ++stats->allocated;
    }
    ~Tracked() { ++stats->destroyed; }
};
template<class T> std::unique_ptr<Tracked<T>> allocate(AllocationStats& stats, const T& value) {
    if (++stats.attempts == stats.fail_at) throw std::bad_alloc();
    return std::make_unique<Tracked<T>>(stats, value);
}

// A single nonmovable owner contains both maps, primary cells, expiry, metadata,
// decoded fixture rows and completed resource bytes. A borrowed view cannot
// outlive this owner. No external mutable backing is accepted or retained.
class PairedPublication {
public:
    enum class State { empty, prepared, publishing, published, refused };
    enum class Error { none, request, collision, allocation, changed, backing };
    enum class MapKind { numeric, name, owner };
    enum class Write { entry, pair, counter, bucket_count, map_count, owner_count };
    using Observer = void(*)(void*, const PairedPublication&, MapKind, Write) noexcept;
    enum class Corruption { row, metadata, primary, expiry, route, pending, short_read, payload };

private:
    struct OwnedMap {
        Map header{};
        std::array<Bucket, bucket_count> buckets{};
        std::array<Node*, capacity> entries{};
        std::array<Node, stock_count> stock{};
        explicit OwnedMap(std::uint32_t first_key) {
            header = {bucket_count, stock_count, capacity, 99,
                reinterpret_cast<std::uintptr_t>(buckets.data()),
                reinterpret_cast<std::uintptr_t>(entries.data())};
            for (std::uint32_t i = 0; i < stock_count; ++i) {
                const auto key = first_key + i;
                const auto bucket = key % bucket_count;
                auto& target = buckets[bucket];
                stock[i] = {static_cast<std::uint32_t>(bucket * 31 + target.count), key, i};
                entries[i] = &stock[i];
                target.pairs[target.count++] = {key, i};
            }
        }
    };
    struct Snapshot {
        Map header{};
        std::array<Bucket, bucket_count> buckets{};
        std::array<Node*, capacity> entries{};
        std::array<Node, stock_count> stock{};
        void capture(const OwnedMap& map) noexcept {
            header = map.header; buckets = map.buckets; entries = map.entries; stock = map.stock;
        }
        bool matches(const OwnedMap& map) const noexcept {
            return std::memcmp(&header, &map.header, sizeof header) == 0
                && std::memcmp(buckets.data(), map.buckets.data(), sizeof buckets) == 0
                && entries == map.entries
                && std::memcmp(stock.data(), map.stock.data(), sizeof stock) == 0;
        }
    };
    struct Addition { std::uint32_t index{}, bucket{}, slot{}; };
    struct MapPlan {
        Snapshot source;
        std::array<Addition, max_new> additions{};
        std::array<std::unique_ptr<Tracked<Node>>, max_new> nodes{};
    };

    AllocationStats& allocations_;
    OwnedMap numeric_{10}, names_{20};
    std::array<const Row*, capacity> primary_{};
    std::array<std::uint64_t, capacity> expiry_{};
    std::array<Metadata, capacity> metadata_{};
    std::array<Request, max_new> expected_{};
    std::array<std::unique_ptr<Tracked<Resource>>, max_new> resources_{};
    std::array<std::unique_ptr<Tracked<Row>>, max_new> rows_{};
    MapPlan numeric_plan_, name_plan_;
    std::size_t added_{};
    std::uint32_t owner_count_{stock_count};
    State state_{State::empty};
    Error error_{Error::none};

    static bool query(const OwnedMap& map, std::uint32_t key, std::uint32_t& value) noexcept {
        if (!map.header.count) return false;
        const auto& bucket = map.buckets[key % bucket_count];
        for (std::uint32_t i = 0; i < bucket.count; ++i) {
            const auto pair = bucket.pairs[i];
            if (pair.key != key || pair.index >= capacity) continue;
            const auto* node = map.entries[pair.index];
            if (node && node->key == key) { value = node->value; return true; }
        }
        return false;
    }
    void discard() noexcept {
        for (std::size_t i = 0; i < max_new; ++i) {
            primary_[stock_count + i] = nullptr;
            expiry_[stock_count + i] = 0;
            metadata_[stock_count + i] = {};
            numeric_plan_.nodes[i].reset(); name_plan_.nodes[i].reset();
            rows_[i].reset(); resources_[i].reset();
        }
    }
    bool refuse(Error error) noexcept {
        discard(); state_ = State::refused; error_ = error; return false;
    }
    bool plan(OwnedMap& map, MapPlan& plan, bool numeric) {
        plan.source.capture(map);
        std::array<std::uint32_t, bucket_count> occupancy{};
        for (std::size_t i = 0; i < bucket_count; ++i) occupancy[i] = map.buckets[i].count;
        for (std::size_t i = 0; i < added_; ++i) {
            const auto& identity = expected_[i].identity;
            const auto key = numeric ? identity.numeric_key : identity.name_key;
            std::uint32_t existing{};
            if (query(map, key, existing)) return false;
            for (std::size_t j = 0; j < i; ++j)
                if (key == (numeric ? expected_[j].identity.numeric_key : expected_[j].identity.name_key))
                    return false;
            const auto bucket = key % bucket_count;
            if (occupancy[bucket] == 31) return false;
            const auto slot = occupancy[bucket]++;
            const auto index = static_cast<std::uint32_t>(stock_count + i);
            plan.additions[i] = {index, static_cast<std::uint32_t>(bucket), slot};
            plan.nodes[i] = allocate(allocations_, Node{
                static_cast<std::uint32_t>(bucket * 31 + slot), key, identity.ordinal});
        }
        return true;
    }
    bool backing_matches() const noexcept {
        for (std::size_t i = 0; i < added_; ++i) {
            const auto ordinal = stock_count + i;
            if (!rows_[i] || !resources_[i]) return false;
            const auto& row = rows_[i]->value;
            const auto& resource = resources_[i]->value;
            const auto& expected = expected_[i];
            if (row.identity != expected.identity || primary_[ordinal] != &row
                || expiry_[ordinal] != 0 || metadata_[ordinal].numeric_key != row.identity.numeric_key
                || metadata_[ordinal].route_index != i || row.resource != &resource
                || !resource.valid() || resource.expected_archive != expected.resource.expected_archive
                || resource.archive != expected.resource.archive || resource.expected != expected.resource.expected
                || resource.offset != expected.resource.offset || resource.archive_size != expected.resource.archive_size
                || resource.payload_size != expected.resource.payload_size) return false;
        }
        return true;
    }
    static void word(std::uint32_t& target, std::uint32_t value) noexcept {
        std::atomic_ref<std::uint32_t>(target).store(value, std::memory_order_release);
    }
    void stores(OwnedMap& map, const MapPlan& plan, MapKind kind, Observer observer, void* context) noexcept {
        auto observed = [&](Write write) noexcept { if (observer) observer(context, *this, kind, write); };
        for (std::size_t i = 0; i < added_; ++i) {
            map.entries[plan.additions[i].index] = &plan.nodes[i]->value;
            observed(Write::entry);
        }
        for (std::size_t i = 0; i < added_; ++i) {
            const auto& addition = plan.additions[i];
            map.buckets[addition.bucket].pairs[addition.slot] = {plan.nodes[i]->value.key, addition.index};
            observed(Write::pair);
        }
        word(map.header.caller_counter, plan.source.header.caller_counter + static_cast<std::uint32_t>(added_));
        observed(Write::counter);
        for (std::size_t i = 0; i < added_; ++i) {
            const auto& addition = plan.additions[i];
            word(map.buckets[addition.bucket].count, addition.slot + 1);
            observed(Write::bucket_count);
        }
        word(map.header.count, plan.source.header.count + static_cast<std::uint32_t>(added_));
        observed(Write::map_count);
    }

public:
    explicit PairedPublication(AllocationStats& allocations) : allocations_(allocations) {}
    PairedPublication(const PairedPublication&) = delete;
    PairedPublication& operator=(const PairedPublication&) = delete;
    ~PairedPublication() noexcept {
        // Remove all owned lookup reachability before reclaiming any owned row,
        // resource or node. This is single-threaded fixture destruction only.
        numeric_.header = {}; names_.header = {};
        numeric_.entries.fill(nullptr); names_.entries.fill(nullptr);
        numeric_.buckets = {}; names_.buckets = {};
        discard();
    }
    State state() const noexcept { return state_; }
    Error error() const noexcept { return error_; }
    std::uint32_t owner_count() const noexcept { return owner_count_; }
    const Map& numeric_map() const noexcept { return numeric_.header; }
    const Map& name_map() const noexcept { return names_.header; }
    bool numeric(std::uint32_t key, std::uint32_t& ordinal) const noexcept { return query(numeric_, key, ordinal); }
    bool name(std::uint32_t key, std::uint32_t& ordinal) const noexcept { return query(names_, key, ordinal); }
    const Row* resolve(std::uint32_t ordinal) const noexcept {
        return ordinal < primary_.size() ? primary_[ordinal] : nullptr;
    }
    bool joined_backing_valid() const noexcept { return added_ && backing_matches(); }

    bool prepare(std::span<const Request> requests) noexcept {
        if (state_ != State::empty) return false;
        if (requests.empty() || requests.size() > max_new) return refuse(Error::request);
        added_ = requests.size();
        try {
            for (std::size_t i = 0; i < added_; ++i) {
                expected_[i] = requests[i];
                const auto& source = expected_[i];
                if (source.identity.ordinal != stock_count + i || !source.identity.numeric_key
                    || !source.identity.name_key || !source.resource.valid()) return refuse(Error::request);
                bool has_identity = false;
                for (const auto byte : source.identity.package) has_identity |= byte != 0;
                if (!has_identity) return refuse(Error::request);
                resources_[i] = allocate(allocations_, source.resource);
                rows_[i] = allocate(allocations_, Row{source.identity, &resources_[i]->value});
                primary_[source.identity.ordinal] = &rows_[i]->value;
                metadata_[source.identity.ordinal] = {source.identity.numeric_key, static_cast<std::uint32_t>(i)};
            }
            if (!plan(numeric_, numeric_plan_, true) || !plan(names_, name_plan_, false))
                return refuse(Error::collision);
        } catch (const std::bad_alloc&) { return refuse(Error::allocation); }
        state_ = State::prepared;
        return true;
    }
    bool publish(Observer observer = nullptr, void* context = nullptr) noexcept {
        // Refuse nested/repeated calls without cleaning up or changing state.
        if (state_ != State::prepared) return false;
        if (!numeric_plan_.source.matches(numeric_) || !name_plan_.source.matches(names_))
            return refuse(Error::changed);
        if (!backing_matches()) return refuse(Error::backing);
        // Both maps and the joined backing are checked before any map write.
        // Everything below is bounded, allocation-free and non-failing. The
        // observer must remain noexcept and must not destroy its active owner.
        state_ = State::publishing;
        stores(numeric_, numeric_plan_, MapKind::numeric, observer, context);
        stores(names_, name_plan_, MapKind::name, observer, context);
        word(owner_count_, static_cast<std::uint32_t>(stock_count + added_));
        if (observer) observer(context, *this, MapKind::owner, Write::owner_count);
        state_ = State::published;
        return true;
    }

    // Explicit pre-publication fault injection for this research-only owner.
    // No mutable backing views or mutation API exist after publication starts.
    bool corrupt_map(MapKind kind) noexcept {
        if (state_ != State::prepared || kind == MapKind::owner) return false;
        auto& map = kind == MapKind::numeric ? numeric_ : names_;
        ++map.header.caller_counter;
        return true;
    }
    bool corrupt_backing(Corruption part) noexcept {
        if (state_ != State::prepared) return false;
        auto& resource = resources_[0]->value;
        switch (part) {
        case Corruption::row: ++rows_[0]->value.identity.numeric_key; break;
        case Corruption::metadata: ++metadata_[stock_count].route_index; break;
        case Corruption::primary: primary_[stock_count] = nullptr; break;
        case Corruption::expiry: expiry_[stock_count] = 1; break;
        case Corruption::route: rows_[0]->value.resource = nullptr; break;
        case Corruption::pending: resource.state = IoState::pending; break;
        case Corruption::short_read: --resource.completed_size; break;
        case Corruption::payload: resource.completed[0] ^= 1; break;
        }
        return true;
    }
};
} // namespace cditem::research
