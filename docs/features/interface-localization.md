# Interface localization

CDMW Full ships its own interface catalogs separately from the game's `.paloc`
string tables. The interface language can be changed in Settings without
restarting the application. The selection is persisted immediately and applies
to existing PySide windows, later-created dialogs and tools, tray and startup
surfaces on the next launch, and the resident .NET Mesh Editor.

## Built-in languages

The selector order and canonical codes are fixed:

| Selector label | Code |
| --- | --- |
| English | `en` |
| Deutsch | `de` |
| Español (España) | `es-ES` |
| Español (Latinoamérica) | `es-419` |
| Français | `fr` |
| Italiano | `it` |
| Português (Brasil) | `pt-BR` |
| Polski | `pl` |
| Русский | `ru` |
| Türkçe | `tr` |
| 日本語 | `ja` |
| 한국어 | `ko` |
| 简体中文 | `zh-Hans` |
| 繁體中文 | `zh-Hant` |

Locale codes are matched case-insensitively and underscores are normalized to
hyphens. Legacy `es` selects `es-ES`. Common Portuguese and Chinese aliases,
including `pt_br`, `zh-cn`, `zh-tw`, `zh-hans`, and `zh-hant`, resolve to their
canonical codes.

The packaged UTF-8 catalogs live in
`cdmw/resources/localization/`. Every built-in catalog must have exactly the
same source keys as English. Source-identical technical terms are explicit
entries and are recorded in `source_identical_terms.json`; they are not silent
fallbacks.

## Custom language packs

Custom JSON files remain partial overlays. Missing values or plural categories
fall back to the corresponding built-in language and then English. A language
that has no built-in catalog falls back directly to English for everything its
custom file does not provide.

Schema version 1 remains accepted:

```json
{
  "schema_version": 1,
  "language_code": "de",
  "language_name": "Deutsch (custom)",
  "translations": {
    "Save": "Speichern"
  }
}
```

Schema version 2 adds plural-category objects while retaining scalar values:

```json
{
  "schema_version": 2,
  "language_code": "pl",
  "language_name": "Polski (custom)",
  "translations": {
    "Save": "Zapisz",
    "{count} files": {
      "one": "{count} plik",
      "few": "{count} pliki",
      "many": "{count} plików",
      "other": "{count} pliku"
    }
  }
}
```

Named placeholders must exactly match the English key in every scalar or plural
branch. Plural categories use the pinned locale rules in
`cdmw/domain/localization.py`; a version-1 or version-2 scalar applies to every
plural category.

Imports are bounded to 16 MiB, 100,000 translation leaves, 4,000 characters per
key, and 100,000 characters per translated value. Invalid UTF-8, JSON, schema
versions, placeholder sets, plural categories, or limits reject the entire
import. Publication is an atomic file replacement and cancellation never
publishes a partial file.

Existing alias-named files are not renamed. When both an alias file and its
canonical-code file exist, the canonical declaration wins and Settings reports
the ignored duplicate.

## Runtime ownership

`cdmw/ui/localization.py` owns the process-scoped live locale, immutable English
source properties, formatting, revisions, top-level registration, and
late-created Qt surfaces. `cdmw/services/startup_localization_service.py`
provides the bounded pre-Qt subset used by external and in-process splash
hosts. Startup remains on the locale selected at launch.

The .NET helper advertises `ui_localization_v1`, its helper-owned source-key
manifest, and the manifest hash. The Python host sends only those keys with the
locale, plural rule, catalog hash, session ID, process generation, request ID,
and localization revision. Initial readiness waits for an acknowledgement that
matches all correlation fields. A live language change updates WinForms
controls without restarting the helper or reloading the model, and reconnect
replays the latest desired locale.

### One owner per string

Several Qt widgets expose the same text through a second child that also reads
it: a `QTabWidget`'s own `QTabBar`, a `QComboBox`'s popup view and its editor,
and the `QHeaderView` over a `QTreeWidget`'s or `QTableWidget`'s headers. Only
the owning widget is translated. Reaching a string through both surfaces
translates the translation, and because each surface keeps its own record of the
English source, the second one stores the rendered text as the source — after
which switching language renders English out of the previous language. Add a
widget kind to `_apply_widget_tree` only after checking which of its children
`findChildren(QWidget)` will also hand back.

Text that the localizer did not write is normally adopted as a new English
source, since it means the app replaced the string. It is not adopted when it
already equals the current language's rendering of the source on record, which
is what lets a widget hold its own translator: set `_i18n_source_<property>`
and then write the translated string.

### Matching rendered text

A string assembled at runtime is matched back against the catalogue's templates
by regex. Scanning all ~2,100 of them was about a millisecond each, which a
language switch pays thousands of times, so they are bucketed by the three
characters an `^`-anchored match must start with, or by three characters of a
literal a match must contain, and each candidate is then rejected by walking its
literals with `str.find` before the regex runs. Both filters are necessary
conditions on a match, never sufficient ones, so the try-order and every result
are unchanged; `rank` carries that single global order across the buckets.

Widgets that ask to be re-translated are drained in one pass per turn of the
event loop, with a queued ancestor absorbing its queued descendants. A queued
widget can be destroyed before the pass runs, and its weak reference will still
resolve, so validity is checked before it is touched.

Human-facing dates, counts, file sizes, and durations use the selected locale.
Paths, hashes, extensions, protocols, editable technical numbers, and
game-provided content remain invariant. CJK locales preserve a configured font
when it covers the script and otherwise use supported Windows UI-font
fallbacks independently in PySide, the splash host, and WinForms. PySide and
the splash host register the matching installed Windows font file when Qt's
offscreen font database does not expose it automatically; no font is bundled.

## Enforcement

Run the reproducible inventory and catalog checks from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\generate_ui_localization_manifest.py --check
.\.venv\Scripts\python.exe scripts\validate_ui_localization_catalogs.py
.\.venv\Scripts\python.exe -m pytest tests\test_localization_catalog_contracts.py
```

Regenerate the source manifest and English catalog only after reviewing a
presentation-string change:

```powershell
.\.venv\Scripts\python.exe scripts\generate_ui_localization_manifest.py --write
```

Every scanner exclusion is stored with its path, symbol, source text, and reason
in `scripts/ui_localization_exclusions.json`. Packaging fails before
PyInstaller when the source manifest is stale or any of the 14 catalogs fails
key, UTF-8, placeholder, plural, rich-text, or accelerator validation.

The automated coverage claim means every CDMW-authored production GUI source
string has an explicit entry in all 14 built-ins and the runtime contracts are
enforced. It does not certify native-speaker style, Windows-owned dialog chrome,
raw external exception bodies, game content, developer harnesses, CLI output,
or visible licensed-asset rendering.

### Auditing what the window actually draws

The checks above run from `source_manifest.json` outwards: every key it lists has
a translation everywhere. They cannot see the opposite failure, which is the one
users report — text that is on screen but was never a key, or is a key the
runtime never looks up. "Production GUI source string" means whatever the
extractor's sink list recognises, so a label composed at runtime or held in a
module constant is absent from the manifest *and* from the thing that checks the
manifest.

`scripts/audit_gui_localization_coverage.py` walks the other way. It builds the
real window offscreen, constructs every lazy tool, and sorts each visible string
into the reason it is still English:

```powershell
.\.venv\Scripts\python.exe scripts\audit_gui_localization_coverage.py --order coverage
.\.venv\Scripts\python.exe scripts\audit_gui_localization_coverage.py --language de --order after
```

`--order coverage` stays in English and reports only strings that no language can
ever change — no catalogue key under any spelling, and no template rule that
matches. `--order after` switches language first and then opens the tools, the
way a user does, and reports strings whose translation exists but did not reach
the screen. `--order before` opens the tools first, so one apply pass covers
everything; a string that fails only under `after` is a lazily-built tree the
localizer did not revisit.

Neither mode is a gate. The counts are large enough that ratcheting them would
lock in the current state rather than describe it.
