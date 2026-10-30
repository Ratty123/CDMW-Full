# Contributing

Thanks for helping improve Crimson Desert Mod Workbench.

## Before You Open An Issue

- Use the latest release or beta build first.
- Check the [CHANGELOG.md](CHANGELOG.md) to see if the problem was already fixed.
- Use `Help > Report a Problem...` to complete the required fields and review a
  redacted local draft. Sending opens a browser verification check and delivers to
  the separate private CDMW inbox; no GitHub account is needed. See
  [reporting setup and privacy](tools/problem_report_receiver/README.md).
- If the issue is a crash or preview failure, you can also use `Help > Export Diagnostics...`
  for manual sharing, or use `Help > Copy Latest Problem Summary`. Review these
  before sharing; public GitHub issues and their attachments are visible to everyone.

## Good Bug Reports

Please include:

- app version, and whether you used the portable EXE or a source checkout
- what you were doing when the problem happened
- expected result vs actual result
- steps to reproduce
- relevant file paths or archive paths, if safe to share
- screenshots or logs when helpful
- game version and platform, mod manager/mods, and whether it also happens without mods
- the diagnostics ZIP or copied problem summary for crashes and preview failures

For preview/build problems, it helps a lot to include:

- the DDS or PNG filename
- whether it came from the archive or a loose file
- the selected backend or workflow mode
- whether crash capture was enabled in `Settings`

## Feature Requests

Feature requests are welcome, especially if they explain:

- the modding workflow you are trying to accomplish
- what is currently awkward or too manual
- what result you want the app to produce

Concrete examples are much more useful than broad tool wishlists.

## Pull Requests

Small, focused pull requests are easier to review than large mixed changes.

Please try to:

- keep the scope narrow
- explain user-facing behavior changes clearly
- mention any affected workflows such as `Textures`, `Create New Item`, `Mesh Editor`, `Research`, or `Archive Browser`
- avoid unrelated cleanup in the same PR
- use the current tool names from the [README](README.md) and update in-app
  documentation when controls or workflows change
- follow the [test guide](tests/README.md) for focused checks; GitHub runs smoke
  and focused contracts by default, with full nonvisual QA available through
  the manual `exhaustive_tests` option

## Research and documentation maintenance

The [Crimson Desert research reference](docs/crimson-desert-research.md) is the
single current public research overview. Source code, schemas and the nearest
feature README own exact implementation contracts. Update those owners and the
affected research sections together when the supported behaviour or evidence
changes; do not create a competing overview.

The GitHub Wiki and **Help > Documentation** are two presentations of the same
manual. Every documentation change must keep both aligned, whether the edit
starts on GitHub, in the app's documentation source, or alongside a feature fix.
This covers every topic, supported workflow, warning, limitation and link in all
14 built-in languages. Layout, navigation and machine-specific path examples can
differ to suit each surface; their instructions and meaning must agree.

The shared sources under `cdmw/ui/shell/about_documentation*.py`, their translation
catalogues and diagnostic reference modules own the content. Follow this workflow
before handing off documentation changes or preparing a rebuild:

1. Read the latest published Wiki revision and preserve any local Wiki edits.
   Generate into a separate directory under `.work/` with
   `.\.venv\Scripts\python.exe scripts/export_github_wiki.py --output <draft-folder>`.
   Compare that output with the published revision before overwriting any files.
2. Reconcile differences in both directions. Port valid GitHub-only edits into
   the shared Help source and all affected translations, then regenerate. Retain
   useful online corrections; resolve conflicting instructions against the owning
   code and evidence. Never treat exporting over unexplained differences as a sync.
3. Run the focused `tests/test_wiki_export.py` checks, the affected localization
   checks, and the export command with `--check`. The exporter refuses unmapped
   Help topics. Check all manuals, sidebars, anchors and diagnostic assets, not
   just the English Home page.
4. Review the complete local Wiki diff. Publish only within the user's authorized
   scope; a request to prepare documentation alone does not authorize a push.
   After publication, verify the actual remote revision with the same export
   `--check` and inspect the affected GitHub-rendered sections.
5. Report source, prepared Wiki, published Wiki and packaged Help separately.
   A local match is not a published match. Existing executables keep the Help
   bundled when they were built, so a source edit or Wiki push cannot update them.
   Keep any pending publication, reconciliation or rebuild explicit; do not claim
   complete alignment until the relevant versions have been checked.

The exporter does not publish. It writes one native-named manual per language,
localized contents sidebars and the language index. Manuals open with Home and
fold the in-article contents for narrow screens. Translated manuals live in locale
folders; public page names and URLs remain stable. Do not recreate separate guide
pages for each locale. Direct Wiki edits must return through the workflow above
so they survive the next export and reach Help as well.

When diagnostic messages change, regenerate the shared Help/Wiki error index
with `python scripts/generate_error_reference.py --write`. Run
`python scripts/audit_error_reference.py` and the focused
`tests/test_error_reference.py` and `tests/test_wiki_export.py` checks. The
independent audit checks exception/log sinks, diagnostic payload fields and
report fragments; add a reproducer when a new emission pattern escapes it.
Check the complete Wiki-owned `reference/<locale>/index.json` and text lists as
well as the rendered manual. The manual links these files because GitHub's page
size limit prevents embedding every message. Runtime/provider error text still
requires the original exception or helper output; a source index cannot promise
to enumerate every possible failure.

To migrate an already published per-guide Wiki without changing its prose, use
`--source-wiki <old-checkout> --output <wiki-folder> --replace-legacy`. This preserves
all guide text and replaces only obsolete generated guide or flat manual files;
keep the old checkout or its Git revision for comparison. Earlier per-guide URLs
become manual URLs with section anchors.

### Confirmed progress

Before handing off a research or implementation task, review whether it changes
a finding, supported operation, refusal boundary, evidence level or open question.
Update the affected reference sections when it does. A rejected hypothesis,
regression or newly identified limitation is also a finding. Routine passing
checks and unrelated presentation changes do not require research edits.

For a changed conclusion, identify:

- **Finding and status:** what is established, implemented, experimental,
  superseded or still unresolved.
- **Evidence:** the actual source/consumer and relevant test, observation or
  inspected input. Identify the confirming source revision and game/build when
  applicable; preserve the scope of historical measurements.
- **Limits:** what the evidence does not establish, failures or blockers, and
  the remaining check needed to strengthen the claim.
- **Review scope:** the material reviewed and its date. Do not imply that
  unrelated sections or old experiments were revalidated.

Keep source, fixture, asset, executable/shader, renderer, packaged, visible-UI
and game evidence separate, using the reference's evidence definitions.
External reports remain attributed reports until independently reproduced.
A plan, assistant summary, remembered result or catalogue label is not a new
verification result.

Correct the current conclusion and its open-question entry rather than appending
a contradictory success paragraph. Retain useful failed approaches as bounded
historical findings. Pin new evidence to the revision that contains it once
available; do not advance every source link or the document-wide baseline merely
because one area changed. A date change alone is not a review.

When format support changes, reconcile the capability manifest, its owning
reader/writer and the reference inventory. Use the existing
[format reporting tool](tools/report_format_decode_progress.py) for its derived
local report. Its catalogue checks do not verify the narrative or game behaviour.

### Archiving superseded material

Age alone does not make a document obsolete. Establish that its implementation
was retired, its plan completed or its current contract replaced. Keep active
plans and unresolved research in their current owners. Preserve any durable
finding or outstanding proof requirement before retiring the old record.

Move historical documents to the local path
`docs/archive/YYYY-MM-DD/<original path relative to docs/>`. Maintain one archive
index at `docs/archive/README.md`, recording the original path, archive date,
reason, current successor and original content hash. Mark each archived document
as historical at the top, retain its original evidence and limitations, rebase
relative links, and repair incoming navigation and real path consumers.

Archived readiness verdicts, measurements and pending checks describe their
original revision. They are not current implementation instructions or proof
that a successor passed those checks. Do not silently mark unresolved work done
when moving a file.

Keep the current `docs/` publication allowlist. Archives, plans, working notes
and machine-local evidence remain ignored; existing tracked documents retain
their status. Never force-add local material or widen publication scope as part
of cleanup. Do not delete useful records merely to reduce clutter.

### Before handoff

- Check changed conclusions, source links, contents anchors and inventory rows
  against the evidence actually reviewed.
- Check archive destinations, incoming links and the current documentation index;
  current navigation must not present an archived record as authoritative.
- Confirm ignore rules and the staged diff expose only intended public files.
  Report which research sections changed, or that the task had no research impact.
- For documentation-only changes, use focused document checks. Do not run
  application suites, native builds or packaging solely to validate prose.

## Project Scope

Crimson Desert Mod Workbench is intentionally centered on:

- archive browsing, preview, extraction, and supported patch workflows
- explicit confirm-before-write archive mutation for supported paths only
- creating equipment identities through Create New Item
- bounded mesh authoring and equipment placement/animation review
- layered texture editing, recolor, upscale, and loose-file DDS/PNG workflows
- rebuild, review, classification, and mod-package export

It does support writing back to game archives for specific supported workflows, but those writes should stay explicit, recoverable, and tightly scoped.

The project does not aim for broad arbitrary archive editing or silent in-place mutation across unsupported formats.
