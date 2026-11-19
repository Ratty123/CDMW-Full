"""Patch-day guards for the game formats no other `real_game` test reads.

The 1.0.0.3732 patch added two ItemInfo fields and Create New Item stopped. Other
readers fail the same quiet way: a mesh, texture, physics or sound reader starts
refusing files, and every owned-fixture test still passes. Each test here runs the
app's own reader over the installed game, so a layout change fails here on patch day.
`tools/patch_day_check.py` runs these with the rest of the `real_game` sweep and maps
every result to an area of the local patch register (`docs/patch-regressions.md`).

Rules every test follows:

- Read-only. Archive entries and the loose `meta/` files are read; nothing is written
  and the game is not launched (`tests/conftest.py` fences the game folder).
- A missing file or an empty sample is a failure, never a skip: a guard that stops
  finding its input has stopped guarding.
- Samples are deterministic (a fixed stride over the sorted paths, plus named
  sentinels), so two runs on one build read the same files and a new failure is the
  build's, not the sample's.
- Floors are invariants with a margin (every file read, byte-identical rebuilds, a
  refusal share), set from the 1.0.0.3732 figures noted beside each test. Raise a
  floor only after reading the new refusals.
- Each check was shown to refuse damaged copies (truncated, or four bytes inserted
  mid-file) of shipped files, except where its docstring says it is weaker
  (`.work/research/2026-11-19-patch-day-coverage/stronger_checks.py` in the main checkout).
- The stride sample rarely lands on files a patch adds; the inventory diff in
  `tools/patch_day_check.py` is what notices those.
"""

from __future__ import annotations

import collections
import os
import re
from pathlib import Path

import pytest

from tests.test_patch_rename_guards import _Game

pytestmark = pytest.mark.real_game


@pytest.fixture(scope="module")
def root() -> Path:
    from tools.placement_studio import corpus

    path = Path(os.environ.get("CDMW_GAME_ROOT") or corpus.game_root())
    if not path.is_dir():
        pytest.skip("needs the installed game")
    return path


@pytest.fixture(scope="module")
def game(root) -> _Game:
    return _Game(root)


@pytest.fixture(scope="module")
def by_extension(game) -> dict[str, list]:
    """Entries per extension, one per normalized path, sorted by path."""

    from tools.placement_studio import corpus

    grouped: dict[str, list] = collections.defaultdict(list)
    for path, entry in sorted(game.by_path.items()):
        grouped[os.path.splitext(path)[1]].append(entry)
    return grouped


def sample(by_extension, extension: str, count: int, sentinels: tuple[str, ...] = ()) -> list:
    """`count` entries at a fixed stride over the sorted paths, plus the named sentinels."""

    entries = by_extension.get(extension, [])
    assert entries, f"the installed game ships no {extension} entries"
    stride = max(1, len(entries) // count)
    chosen = entries[::stride][:count]
    by_path = {_norm(e.path): e for e in entries}
    for path in sentinels:
        assert path in by_path, f"the installed game no longer ships {path}"
        if by_path[path] not in chosen:
            chosen.append(by_path[path])
    return chosen


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/").lower()


def _refusals(game, entries, check) -> tuple[int, list[tuple[str, str]]]:
    """Run `check(data, path)` on each entry; return (checked, [(path, reason)] refusals)."""

    refused = []
    for entry in entries:
        path = _norm(entry.path)
        try:
            reason = check(game.read_entry(entry), path)
        except Exception as error:  # a reader that raises is a refusal, with its message
            reason = f"{type(error).__name__}: {error}"
        if reason:
            refused.append((path, str(reason)[:200]))
    return len(entries), refused


def _assert_share(name: str, checked: int, refused: list, *, at_most: float) -> None:
    share = len(refused) / checked if checked else 1.0
    reasons = collections.Counter(reason.split(":")[0][:80] for _path, reason in refused)
    print(f"{name}: {checked - len(refused)}/{checked} read; refusals {dict(reasons.most_common(5))}")
    assert checked, f"{name}: nothing was checked"
    assert share <= at_most, (f"{name}: {len(refused)} of {checked} refused (allowed {at_most:.0%}); "
                              f"first: {refused[:5]}")


# --------------------------------------------------------------------------- archives


def test_every_package_table_parses(root):
    """Every `.pamt` under the game parses; the browser would otherwise drop a whole package quietly.

    `corpus._iter_archive_entries` and the browser skip a table that will not parse, so a new
    index layout ([P-01]) shows up only as missing files. 1.0.0.3732: 73 tables, 9 of them
    empty DLC placeholders with no archive.
    """

    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    tables = list(discover_pamt_files(root))
    assert len(tables) >= 30, len(tables)
    failed, empty = [], []
    for pamt in tables:
        try:
            entries = parse_archive_pamt(pamt)
        except Exception as error:
            failed.append((str(pamt), f"{type(error).__name__}: {error}"))
            continue
        # A DLC folder may hold a 33-byte table and no archive; an empty table beside archives is a break.
        if not entries and any(pamt.parent.glob("*.paz")):
            empty.append(str(pamt))
    assert not failed, failed[:5]
    assert not empty, empty[:5]


@pytest.mark.parametrize("relative", ["meta/0.paver", "dlc/dlc_01/meta/0.paver"])
def test_paver_reads_a_version_label(root, relative):
    """PAVER gives Mod Management its game version label ([P-04], [P-30]).

    1.0.0.3732: both read `2.05.00` from 28 bytes (DLC records before the build bytes).
    """

    from cdmw.core.mod_compatibility import decode_paver_build

    raw = (root / relative).read_bytes()
    label = decode_paver_build(raw)
    print(relative, len(raw), label)
    assert re.fullmatch(r"\d+\.\d{2}\.\d{2}", label), (relative, len(raw), label, raw.hex())


@pytest.mark.parametrize("relative", ["meta/0.papgt", "dlc/dlc_01/meta/0.papgt"])
def test_papgt_lists_every_shipped_package(root, relative):
    """The mount list still reads, in the compact layout, and lists the shipped package folders ([P-06]).

    CDMW refuses to rewrite a compact list; a new layout must be looked at before that refusal
    is trusted again. 1.0.0.3732: 735 bytes each.
    """

    from cdmw.core.papgt_format import is_compact_papgt, read_papgt_directories

    raw = (root / relative).read_bytes()
    assert is_compact_papgt(raw), (relative, len(raw), raw[:16].hex())
    directories = read_papgt_directories(raw)
    names = {d.name.strip("/").lower() for d in directories}
    print(relative, len(raw), len(directories))
    assert len(directories) >= 30, (relative, len(directories))
    base = root if relative.startswith("meta/") else root / "dlc" / "dlc_01"
    shipped = {p.name.lower() for p in base.iterdir() if p.is_dir() and (p / "0.pamt").is_file()}
    missing = sorted(shipped - names)
    assert not missing, (relative, missing[:10])


@pytest.mark.parametrize("relative", ["meta/0.pathc", "dlc/dlc_01/meta/0.pathc"])
def test_texture_registry_parses_and_rebuilds(root, relative):
    """Both texture registries parse and rebuild byte for byte ([P-20]).

    Texture replacement and generated icons register DDS files here. The DLC registry had
    never been parsed by a test. 1.0.0.3732: base 7,581,189 bytes, DLC 1,886,183 bytes.
    """

    from cdmw.core.pathc_format import encode_pathc, parse_pathc

    raw = (root / relative).read_bytes()
    table = parse_pathc(raw)
    count = len(table.entries)
    print(relative, len(raw), count)
    assert count >= 1000, (relative, count)
    assert encode_pathc(table) == raw, f"{relative} no longer rebuilds byte for byte"


# --------------------------------------------------------------------------- textures


def test_dds_headers_inspect(game, by_extension):
    """The DDS header reader understands shipped textures (texture editor, previews, replacement)."""

    from cdmw.core.dds_native import inspect_dds_native
    from cdmw.core.pathc_format import validate_dds_payload

    def check(data, _path):
        info = inspect_dds_native(data, payload_size=len(data))
        if not (info.width and info.height) or info.reason:
            return f"refused: {info.reason or info.format_name}"
        validate_dds_payload(data)  # the header explains every byte (a damaged copy fails here)
        return ""

    checked, refused = _refusals(game, sample(by_extension, ".dds", 400), check)
    _assert_share("dds", checked, refused, at_most=0.02)


# --------------------------------------------------------------------------- meshes and skeletons


def test_character_meshes_parse(game, by_extension):
    """The Python mesh parser reads shipped `.pac` meshes completely (Mesh Editor, Refit, replacement).

    Uses the PAC corpus harness's own report, so `unsupported_or_incomplete` (a submesh whose
    counts disagree with its buffers) counts as a refusal. 1.0.0.3732: 120 of 120.
    """

    from tools.pac_parser_corpus_harness import _entry_report

    refused = []
    entries = sample(by_extension, ".pac", 120)
    for entry in entries:
        report = _entry_report(entry)
        if report["status"] != "ok":
            detail = report.get("error") or [i.get("code") for i in report.get("issues", [])][:3]
            refused.append((report["path"], f"{report['status']}: {detail}"))
    _assert_share(".pac", len(entries), refused, at_most=0.03)


@pytest.mark.parametrize("extension", [".pam", ".pamlod"])
def test_static_meshes_parse(game, by_extension, extension):
    """Static and LOD meshes parse to geometry (previews, static replacement, Format Explorer).

    The PAC harness's source-map checks do not apply to these, so the guard is only that the
    parser returns vertices. It is weak: a copy with four bytes inserted mid-file still
    parses, so this catches a header or section-table change, not a vertex layout drift.
    All-zero proxy PAMs exist ([P-05]), hence the margin.
    """

    from cdmw.modding.mesh_parser import parse_mesh

    def check(data, path):
        mesh = parse_mesh(data, path)
        return "" if mesh.total_vertices > 0 and mesh.submeshes else "no geometry"

    checked, refused = _refusals(game, sample(by_extension, extension, 100), check)
    _assert_share(extension, checked, refused, at_most=0.05)


def test_skeletons_read_and_rebuild(game, by_extension):
    """Every shipped `.pab` reads with the strict reader and rebuilds byte for byte.

    Skeletons drive skinning, Refit, Placement Studio and animation export. 1.0.0.3732: 269 files.
    """

    import scripts.pab_corpus_check as pab_check

    def check(data, path):
        row = pab_check.check(data, path)
        problems = [k for k in ("round_trip", "hashes_match", "append_rereads") if row.get(k) is False]
        return row.get("error") or ",".join(problems)

    entries = by_extension.get(".pab", [])
    assert len(entries) >= 200, len(entries)
    checked, refused = _refusals(game, entries, check)
    _assert_share("pab", checked, refused, at_most=0.0)


# --------------------------------------------------------------------------- physics


def test_hkx_tagfiles_round_trip(game, by_extension):
    """The HKX tagfile codec parses, rebuilds and relocates shipped physics files exactly."""

    from tools.hkx_tagfile_corpus_harness import check_hkx_bytes

    def check(data, _path):
        row = check_hkx_bytes(data)
        if row["status"] == "exact":
            return ""
        return f"{row['status']}: {row.get('code', '')}"

    checked, refused = _refusals(game, sample(by_extension, ".hkx", 80), check)
    _assert_share("hkx", checked, refused, at_most=0.10)


# --------------------------------------------------------------------------- materials, appearance, prefabs


def test_pac_xml_sidecars_parse(game, by_extension):
    """Material sidecars (`.pac_xml`) parse into texture references (material editor, texture lookup)."""

    from cdmw.core.pac_xml_references import parse_pac_xml_references

    def check(data, _path):
        refs = parse_pac_xml_references(data)
        return "" if refs is not None else "no result"

    checked, refused = _refusals(game, sample(by_extension, ".pac_xml", 300), check)
    _assert_share("pac_xml", checked, refused, at_most=0.02)


def test_appearance_xml_lists_prefabs(game, by_extension):
    """Character appearance files (`.app_xml`) still name their prefabs (appearance composite, NPC armour)."""

    from cdmw.core.appearance_composite import _parse_appearance_prefabs

    def check(data, _path):
        nodes = _parse_appearance_prefabs(data.decode("utf-8-sig", errors="replace"))
        return "" if nodes else "no prefab nodes"

    checked, refused = _refusals(game, sample(by_extension, ".app_xml", 200), check)
    _assert_share("app_xml", checked, refused, at_most=0.10)


def test_prefabs_decode(game, by_extension):
    """The prefab reader decodes shipped prefabs (New Item, Placement, sockets, part roles) ([P-21])."""

    from cdmw.core.prefab_binary import decode_prefab_binary, walk_is_determined

    def check(data, _path):
        decode_prefab_binary(data)
        # A completed decode alone proved little in P-21; the walk must also be determined.
        return "" if walk_is_determined(data) else "walk not determined"

    sentinels = ("character/bin__/prefab/1_pc/1_phm/weapon/cd_phm_00_sword_0001.prefab",)
    sentinels = tuple(s for s in sentinels if s in game.by_path)
    checked, refused = _refusals(game, sample(by_extension, ".prefab", 300, sentinels), check)
    _assert_share("prefab", checked, refused, at_most=0.02)


# --------------------------------------------------------------------------- effects and sound


@pytest.mark.parametrize("extension", [".pae", ".paem"])
def test_effects_decode(game, by_extension, extension):
    """Effect and emitter binaries decode (effect catalogue, New Item effects) ([P-28])."""

    from cdmw.core.effect_binary import decode_effect_binary
    from cdmw.core.effect_writer import serialize_effect

    def check(data, _path):
        return "" if serialize_effect(data, decode_effect_binary(data)) == data else "does not rebuild byte for byte"

    checked, refused = _refusals(game, sample(by_extension, extension, 150), check)
    _assert_share(extension, checked, refused, at_most=0.02)


def test_sound_banks_read(game, by_extension):
    """Wwise banks read their chunks and object graph (sound preview and bank editing)."""

    from cdmw.core.archive_wwise_bank import is_sound_bank, read_bank_chunks
    from cdmw.core.archive_wwise_hirc import read_hirc_graph

    def check(data, _path):
        if not is_sound_bank(data):
            return "not a bank"
        chunks, _ = read_bank_chunks(data)
        if not chunks:
            return "no chunks"
        if chunks[-1].offset + chunks[-1].size != len(data):
            return "chunks do not end the file"
        if any(c.identifier == "HIRC" for c in chunks):
            read_hirc_graph(data)
        return ""

    checked, refused = _refusals(game, sample(by_extension, ".bnk", 80), check)
    _assert_share("bnk", checked, refused, at_most=0.02)


# --------------------------------------------------------------------------- text


def test_every_shipped_text_language_is_known(game):
    """Each language the game ships text for is one New Item patches and names ([P-33]).

    1.0.0.3663 added Arabic: Create New Item has to patch every language's `item.paloc`, and
    the identity panel needs a name for each. A 16th language should fail here, not ship
    unpatched. 1.0.0.3732: 15 folders under `gamedata/stringtable/binary__/`.
    """

    from cdmw.domain.new_item.rules import LOCALIZATION_LANGUAGES
    from cdmw.ui.new_item.panels_identity import LANGUAGE_LABELS

    prefix = "gamedata/stringtable/binary__/"
    shipped = {path[len(prefix):].split("/", 1)[0] for path in game.by_path
               if path.startswith(prefix) and path.endswith("/item.paloc")}
    print("languages", sorted(shipped))
    assert len(shipped) >= 15, sorted(shipped)
    assert shipped == set(LOCALIZATION_LANGUAGES), (sorted(shipped - set(LOCALIZATION_LANGUAGES)),
                                                    sorted(set(LOCALIZATION_LANGUAGES) - shipped))
    assert not shipped - set(LANGUAGE_LABELS), sorted(shipped - set(LANGUAGE_LABELS))


# --------------------------------------------------------------------------- gameplay tables, one node per table


def _decoded_tables() -> list[str]:
    from cdmw.core.static_table_records import DECODED_TABLES

    return sorted(DECODED_TABLES)


#: Tables the schema still knows that the game no longer ships, with the build that retired them.
RETIRED_TABLES = {
    "detectdetailinfo": "folded into DetectInfo._detectDetailData after 1.0.0.3576 (not shipped on 1.0.0.3663)",
}


@pytest.fixture(scope="module")
def static_pairs(game) -> dict[str, dict[str, bytes]]:
    root = "gamedata/binarystaticinfo__/bin/"
    pairs: dict[str, dict[str, bytes]] = {}
    for path, entry in game.by_path.items():
        if path.startswith(root) and path.endswith((".staticinfoheader", ".staticinfobody")):
            stem, _, ext = path[len(root):].rpartition(".")
            pairs.setdefault(stem, {})[ext] = game.read_entry(entry)
    assert len(pairs) >= 200, len(pairs)
    return pairs


@pytest.mark.parametrize("table", _decoded_tables())
def test_static_table_decodes(static_pairs, table):
    """Each gameplay table the app has a schema for decodes, base and DLC layer ([P-08], [P-31]).

    `test_static_table_records.py` stops at the first table with an open refusal, so one known
    break hid every later one. Here each table is its own result, and the patch-day baseline
    lists the tables already known to refuse rows. 1.0.0.3732: 305,276 rows decode; the open
    refusals are in detectinfo, factionspawndatainfo, missioninfo, skillgroupinfo,
    spawningpoolautospawninfo, stageinfo, statusinfo and uimaptextureinfo.
    """

    from cdmw.core.static_table_records import LEGACY_TABLE_STEMS, decode_static_table

    if table in RETIRED_TABLES:
        assert table not in static_pairs, f"{table} ships again; drop it from RETIRED_TABLES"
        return
    stems = [s for s in static_pairs if LEGACY_TABLE_STEMS.get(s.split(".", 1)[0], s.split(".", 1)[0]) == table]
    assert stems, f"the game no longer ships {table} under its name or a legacy name ([P-09])"
    closed = ("This compact static variant has not been qualified.", "Unsupported compact static discriminant.")
    for stem in sorted(stems):
        pair = static_pairs[stem]
        if not pair.get("staticinfobody"):
            continue
        result = decode_static_table(table, pair["staticinfoheader"], pair["staticinfobody"])
        open_refusals = collections.Counter(reason for _key, reason in result.refused if reason not in closed)
        print(f"{stem}: {len(result.records)} decoded, {len(result.refused)} refused")
        assert not open_refusals, (stem, len(result.records), dict(open_refusals.most_common(3)))
