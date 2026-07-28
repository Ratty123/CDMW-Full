# Translation Studio

Every line of text in the game, searchable and retranslatable, exported as a mod.

`.paloc` has been readable and writable for a while — 14 languages, 187,521 lines each,
byte-exact round trip. But there was no way to reach it from the app, so the one format
where an edit provably **cannot** corrupt anything was also the one nobody could use.
This is the missing half.

Owners: `tools/translation_studio/catalogue.py` (domain), `language_index.py` (finding the
tables), `table_model.py` (the virtualised table), `tab.py` (the panel), and the AI layer
in `ai_provider.py` / `ai_translate.py` / `ai_job.py` / `ai_panel.py`, over
`cdmw/core/paloc_format.py`. Registered as a lazy tool tab in
`cdmw/ui/shell/tool_tabs.py`. Tests: `tests/test_translation_studio.py`.

## Why an edit here is safe

Nothing in `.paloc` is offset-addressed, aligned, or checksummed: it is a flat run of
`(category, key, text)` records with the count in a footer. A translated line may be any
length and rewriting the table is just re-emitting the records. That makes this the
lowest-risk modding surface in the game — and the highest-volume one, since translations,
renamed items and rewritten quest text are all the same operation.

## What the data shape dictates

**Search first, browse never.** 187,521 lines is not a list anyone scrolls, so the panel
opens on a search box. Search is a plain case-insensitive scan over key and text, which
filters the whole table in about 32 ms — faster than a keystroke. An index would need
building, invalidating on every edit and keeping correct, and would buy nothing a person
could perceive.

**A virtualised model, not a widget table.** `QTableWidget` would build 187,521 row
widgets up front. `QAbstractTableModel` builds nothing and answers only for the cells on
screen: the model is ready in 96 ms and a filter swap costs about 1 ms. The model holds a
*view* — a tuple of entry indexes — so filtering never touches the underlying table.

**One language in memory, plus one reference.** The tables are 16–25 MB each; loading all
fourteen would cost 250 MB for a feature nobody uses at once. One working language and
one optional reference is what a translator actually needs.

**Edits held apart from the table.** A pass touches a handful of lines out of 187,521, so
edits live in their own small mapping and fold into the document only on export. That
keeps "what have I changed" answerable, and Reset free.

## The panel

- **Language** and **Show alongside** pickers, then Load. Reading happens on a worker;
  a 16 MB table must not stall the UI thread.
- **Find**, a **Group** filter (the category ids, labelled from the data), and **Edited
  only**. Results are capped at 5,000 — nobody reads 90,000 hits, and building that view
  costs more than the search.
- **Key · Group · Text · Reference**. Text is editable in place by double-click; the
  other three are not.
- **Edited rows are highlighted**, and the shipped text stays in the cell's tooltip so
  the original is never lost from view.
- **Revert line** and **Reset all**, **Translate with AI** and **AI settings**, then mod
  name/author and one Export button that writes a package per manager. Disabled until
  something changes.

The reference column is the feature that makes this a translation tool rather than a
string editor: translating into Polish means reading the English, and proofreading a fan
translation means reading the Korean original. Only the key-to-text mapping is kept, not
a second editable table.

## Finding the tables costs more than reading them

Opening the tab took about 3.6 seconds, and pressing Load paid the same 3.6 seconds
again. Both went to the same question — *which package holds this language?* — answered
by parsing all 33 package tables.

Almost all of that is waste. The fourteen `.paloc` tables live in packages 0019–0032,
which hold **one entry each** and parse in under a millisecond; the time goes to 0000,
0004 and 0009, which carry 200,000–400,000 entries apiece and not one localization string
between them. Nothing can know that without parsing, so `language_index.py` parses once
and caches the answer in `workspace/translation_studio/language_index.json`, keyed on the
package files' own sizes and modification times.

Warm, listing the languages is one `stat` per package — 11 ms — and `read_language` parses
the single one-entry table that actually holds the language. Cold, the sweep runs on a
worker and the tab opens immediately with "Listing the languages in the archives (first
time only)". Measured on the installed game: constructor 3.7 s → **0.14 s**, Load
3.6 s → **0.69 s** including the 16 MB parse and a reference language.

The cache is derived and always safe to delete. A stale one is never *used* — the
fingerprint has to match first — so the worst it can cost is a rebuild.

## Translating, not just editing

The panel could always rewrite a line by hand, which is the wrong tool for 187,521 of
them. **Translate with AI** sends the lines you have filtered to a model on **your own API
key** and writes the replies into the same edit map a hand edit uses — so a machine
translation is highlighted, revertable, and exported by the same button as everything
else.

**Bring your own key, because the volume makes it the only honest option.** Three request
shapes cover the field and everything else is a base URL: Anthropic (`/v1/messages`),
OpenAI (`/v1/chat/completions` — which OpenRouter, DeepSeek, Groq, Together, LM Studio and
Ollama all speak, so "OpenAI-compatible" is one preset rather than eight), and Google
Gemini (`:generateContent`). A local model needs no key at all.

There is deliberately **no OAuth**. A ChatGPT or Claude subscription login is not an API
credential — neither provider issues API keys through a public OAuth flow — so offering a
"sign in with…" button would be promising something that cannot work.

**Keys are encrypted to the Windows account** through DPAPI, so the file in the workspace
is useless to another account or on another machine. Where DPAPI is unavailable the key is
written plainly and the dialog *says so*, because silently pretending otherwise is worse
than the warning.

### What the data shape dictates here too

**Markup is what actually breaks.** `<br/>` appears 23,751 times in the English table,
`{Key:Key_Skill_1}` 824 times, `{Money:Money_Copper:1}` 246. A model that helpfully
renders `{Key:Key_Roll}` as `{Tangent:Key_Roll}` produces a line that reads fine in the
editor and shows a literal brace-string in the game. So every reply is checked against its
source — same tokens, same count of each — and a line whose markup changed is **reported
rather than applied**. `[EMPTY]` is protected as a sentinel; `[Effect]` is not, because
that one is prose the player reads.

**Batches, ids, and partial application.** Lines go up in batches because one request per
line would re-send the instructions 187,521 times; each line carries a numeric id so a
reply can arrive incomplete or reordered and still land on the right rows; and each batch
is applied to the catalogue *as it lands*, so Stop after twenty minutes leaves twenty
minutes of translation in the table rather than nothing.

**Scope is never implicit.** The dialog lists the selected line, the lines on screen, the
whole search, and the whole table with counts beside each, and asks again above 2,000
lines. The difference between "the twelve lines I searched for" and "all 187,521" is the
difference between a few cents and a bill worth noticing.

**A rate limit is not a failure.** 429 and 5xx retry with backoff, honouring `Retry-After`;
the sleep is sliced so Stop still answers. A bad key is not retried — it will not get
better — and the provider's own message is what the log shows.

The group label rides along with each line as context, because "Item name" and "Quest
dialogue" are translated differently and the model cannot tell them apart from the text.

### The language slot

The export replaces the table for the language you **loaded**, whatever you translated
*into*. Translating English into Swedish and exporting produces a mod that overwrites the
English table — so the game stays set to English and shows Swedish. The dialog says this
in as many words, because it is the one part of the workflow that is not self-evident.

## Traps worth recording

The filter handler reconnected `selectionChanged` on every refresh, which stacked one
duplicate slot per keystroke. The connection belongs with `setModel`, which is what
replaces the selection model. A test asserts the receiver count does not grow while
filtering, because nothing else about the UI would have looked wrong.

Moving the language sweep onto a worker introduced a second one. A `QThread` parented to
the tab is destroyed with the tab, and destroying a *running* `QThread` is an access
violation — which is exactly what closing or reloading the tab mid-sweep would do. It
showed up as a `Windows fatal exception: access violation` in the test run, not in the
panel. The worker threads are unparented and held in a module-level set until they finish;
Qt severs the signal to the dead receiver on its own.
