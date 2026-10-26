# CDMW Item Composer

A portable C++20 port of `cdmw/domain/archives/overlay_merge.py` and the codecs it
composes with. It is the first step of milestone 2 of the `.cditem` ASI loader: the
virtual loader will compose installed packages into the current game files at launch,
without CDMW's Apply step. Nothing here touches the platform, the file system or an
archive; callers pass bytes in and get bytes back.

`merge_overlay_files(before, after, current)` applies one owned change onto the current
files, as the Python function of the same name does, with the same results:

- whole files: unchanged, added, removed, or a conflict when both installs write one;
- `.pabgb`/`.pabgh` and `.staticinfobody`/`.staticinfoheader` table pairs merged by
  primary key, with the directory width search of `parse_pabgh_table` kept exactly;
- `storeinfo` rows merged per shop entry, including independently appended entries that
  share an order index, and `itemgroupinfo` rows merged per member;
- `.paloc` merged per key, numeric keys placed by the leading ascending run, and the
  512-byte LZ4 container kept or rewritten;
- `partprefabtable.pappt` (both record layouts), `meta/0.pathc` and
  `ui/xml/texture/cd_item_icon.xml` merged per record.

It also writes what a composition is installed as:

- `build_overlay_archive(files)`: one archive directory (`0.pamt` and `0.paz`) holding only
  the given stored payloads, with the folder and name tries, alignment and checksums of
  `archive_overlay.build_overlay_archive`;
- `parse_papgt`, `serialize_papgt` and `papgt_with_directory`: the mount list that puts
  that directory ahead of the shipped ones;
- `pa_checksum` and `hashlittle`, the lookup3 hashes both formats use;
- `stored_payload` and `crypt_chacha20`: an entry's stored bytes as `archive_patching`
  writes them (LZ4 type 2, ChaCha20 keyed by the file name), refusing as Python's
  `cryptography` does a payload whose block counter would pass 2^32.

And it reads what the game would read before the composition:

- `parse_pamt`: `parse_archive_pamt_bytes`, its name-trie walk (cycles, truncation and the
  resolver caches included) and folder-range assignment;
- `read_entry`: `read_archive_entry_data` for the tables, string tables and XML a
  composition touches, decrypting first, then validating the plaintext as Python does
  (paloc by parsing, everything else by its exact plain-text and structured-binary
  checks, with XML that is flagged encrypted but stored plain kept as is), then
  decompressing. In game 2.03.02 the part-prefab table and the icon registry are stored
  ChaCha20 and LZ4, the static-info tables LZ4 only, and item names sit in the
  per-language `gamedata/stringtable/binary__/<language>/item.paloc`;
- `MountedArchives`: the groups `meta/0.papgt` lists, in its order, read from
  `<root>/<group>/0.pamt`; the first group holding a path wins. Unlike CDMW's archive
  catalogue, which skips DMM's `dmmsa` and `dmmgen` folders by default, this includes
  them, as the game does, so a composition builds on DMM's edits instead of hiding them.
  Directories the list does not name are not mounted.

It composes a private view at launch:

- `compose_view(root, packages, group)`: each package's owned changes (`Change`: before,
  after, archive flags, mount-metadata mark) merge in order onto what the game reads
  today, through `MountedArchives` and `meta/0.pathc`. The changed files become the
  private group `group`, mounted first in the published `meta/0.papgt`, beside the
  composed `meta/0.pathc`: `prepare_profile`'s tail for packages without field or texture
  operations. The view also lists every file it was built from (the mount list, each
  listed group's `0.pamt`, `meta/0.pathc` and each `.paz` an underlay entry came from)
  for a cache key, and its stage times;
- `free_group_name`: `overlay_directory_name` for a fresh overlay, the first free
  four-digit name from 0036 that is neither a folder nor a mount-list entry;
- `parse_change_set`: one package's changes from a `CDMWCHG1` change set file, the
  provisional launch-time input until packages carry `runtime/` members: u32 change
  count, then per change u32 + UTF-8 path, u8 + (u64 + bytes) before, u8 + (u64 +
  bytes) after, u64 flags and u8 mount-metadata mark. A truncated, repeated, trailing
  or out-of-range record is a `FormatError`.

And it reads `.cditem` packages:

- `ZipArchive`: `zipfile.ZipFile` as `independent_item_package` uses it: the end-record
  search, prepended data, name sanitizing (cut at NUL, backslashes to slashes), Info-ZIP
  Unicode path fields, matching local-header names, the overlap check (with zipfile's
  warn-only case for a shared header offset), CRC-32 and the member size check;
- `inflate`: raw DEFLATE that accepts and refuses the streams zlib does;
- `sha256` and `crc32`.

Failures keep Python's kinds: `OverlayConflict` where Python raises `OverlayConflict`, and
`FormatError` where it raises anything else. `Unsupported` marks input outside the subset
this port reproduces exactly, so a caller refuses instead of guessing:

- icon registry XML with entity or character references, CDATA, processing instructions,
  declarations, non-ASCII element or attribute names, or non-ASCII `Name`/`Filename`
  values (Python's case folding and expat's full grammar are not modelled);
- a localization key made only of non-ASCII characters and ASCII digits, which Python's
  `str.isdigit` might read as a number;
- repeated `meta/0.pathc` checksums, which Python's tuple sort may refuse;
- overlay paths that are not UTF-8;
- archive entries the composer does not read: DDS, partial PAR containers, non-ASCII
  names under ChaCha20, and a mount list that names a directory twice;
- ZIP64, cp437 member names outside ASCII, bzip2, LZMA and Zstandard members, and a
  DEFLATE member whose stream runs past its directory size or ends unfinished there
  (zipfile truncates at that size, so whether zlib would have flagged the rest depends on
  its internal state).

## LZ4

`lz4::decompress` accepts the blocks python-lz4 1.9.4's `LZ4_decompress_safe` accepts for
a full-size decode, including its end-of-block rules and zero-filled offset-0 matches.
`lz4::compress` reproduces `lz4.block.compress(data, store_size=False)` byte for byte:
python-lz4 compresses every input size the way liblz4 does with a 32-bit position table
(5-byte hash, 12-bit table, 64 KiB window), never with the 16-bit small-input table.
Composed payloads and rewritten `.paloc` containers therefore match Python exactly.

## Build and test

```powershell
cmake -S native/cdmw_item_composer -B native/cdmw_item_composer/build -A x64
cmake --build native/cdmw_item_composer/build --config Release
ctest --test-dir native/cdmw_item_composer/build -C Release --output-on-failure
.\.venv\Scripts\python.exe -m pytest tests/test_native_overlay_merge.py tests/test_native_archive_writer.py tests/test_native_archive_reader.py tests/test_native_package_reader.py tests/test_native_composition.py -q
```

These run every case through both implementations and compare the bytes; they skip when
the CLI is not built. Their three `real_game` tests read the shipped tables through the
mount list, merge two installs over them, and compose two packages over the installed
game; they need explicit opt-in (`-m real_game`) and only read the game folder. On
2026-10-26 all three passed on game 2.03.02 with DMM's group mounted, the composition
publishing 11 files (9.3 MB) in one Python and one native pass of 10.4 s together.

`tools/compose_cli.cpp` is a test driver only. The virtual loader links the library
(its CMake adds this directory for the library target alone) with the same static
runtime and warning settings, and composes at launch; see its README.

On 2026-10-26 the five applied Wolf Trial packages (no field or texture operations)
were taken from CDMW's own resolve, written as five change sets and composed with
`compose-sets` over game 2.03.02 with DMM's group mounted. The result was
byte-identical to the view CDMW's Apply had published for them: `meta/0.papgt`, the
170-file group `0042` (193 MB `0.paz`) and `meta/0.pathc`. CDMW's Python takes about
107 s for that profile (80 s of it resolving the packages). The native composition
takes 3.9 to 4.5 s end to end, reading the 546 MB of change sets included: about
0.8 s reads and validates the 36 mounted PAMTs (65 MB) in parallel while indexing
only the touched paths, and 2.0 to 2.3 s merges each file's chain over the five
packages in parallel, `meta/0.pathc` being the longest. A failure is still reported
as the sequential order meets it first. `compose_view(..., parallel = false)` does
the same work on the calling thread (about 6.2 s here); the virtual loader composes
that way, because on the game's startup path worker threads do not run until its
initialization returns. The change sets hold full before/after
tables, 109 MB per package; patch 0004's reduced records would shrink them and the
merge's before/after side, but not the current-side parse.

## Not yet ported

The package `runtime/` members (patch 0004's `minimal_changes()` output and a parser
that turns them into `Change` records) replace the provisional change sets.
`cdmw_archive_core` was not reused for reading: its scan sorts groups instead
of following the mount list, and its decoder skips Python's plaintext validation.
Packages with field or texture operations (`prepare_fields` / `prepare_textures`) are out
of scope for v1.
