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
- `pa_checksum` and `hashlittle`, the lookup3 hashes both formats use.

Failures keep Python's kinds: `OverlayConflict` where Python raises `OverlayConflict`, and
`FormatError` where it raises anything else. `Unsupported` marks input outside the subset
this port reproduces exactly, so a caller refuses instead of guessing:

- icon registry XML with entity or character references, CDATA, processing instructions,
  declarations, non-ASCII element or attribute names, or non-ASCII `Name`/`Filename`
  values (Python's case folding and expat's full grammar are not modelled);
- a localization key made only of non-ASCII characters and ASCII digits, which Python's
  `str.isdigit` might read as a number;
- repeated `meta/0.pathc` checksums, which Python's tuple sort may refuse;
- overlay paths that are not UTF-8.

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
.\.venv\Scripts\python.exe -m pytest tests/test_native_overlay_merge.py tests/test_native_archive_writer.py -q
```

Both test files run every case through both implementations and compare the bytes; they
skip when the CLI is not built. The `real_game` test in `test_native_overlay_merge.py`
composes two installs over the shipped tables and needs explicit opt-in (`-m real_game`).

`tools/compose_cli.cpp` is a test driver only; the library is meant to be linked into the
virtual loader, which builds with the same static runtime and warning settings.

## Not yet ported

Reading the effective current files through the PAPGT order (with `cdmw_archive_core`'s
PAMT, PAZ, LZ4 and ChaCha20 readers), producing stored payloads for the overlay, and the
package `runtime/` members are the next steps.
Packages with field or texture operations (`prepare_fields` / `prepare_textures`) are out
of scope for v1.
