# Research

Owns Texture Research UI, archive reference inspection, and research notes
presentation. Long scans and enrichment belong in workers/services.

UI modules use contracts and pure state rules from `cdmw/domain/research/` and
operations from the composed `ResearchService`. `cdmw.core.research` remains a
public compatibility facade and is not an implementation dependency here.

Mip/normal row details use a debounced, cancellable latest-wins worker. Report
rows are frozen before dispatch; serialization is cancellable and publishes by
atomic replacement, so cancellation or failure preserves an existing report.
Archive previews and reference scans stay in cancellable workers; note files
also publish atomically.

When Archive Browser publishes a standalone-v2 session, Research requests a
bounded candidate view from the resident archive worker instead of reading the
legacy process-wide catalogue. It pages a bounded, ordered prefix of the current
query so the archive picker retains non-texture rows. A separate bounded lookup
finds image and reference candidates throughout that query, even beyond the
picker prefix, and a third session-scoped lookup supplies text sources needed
for cross-reference analysis. Those text sources are materialized under
per-file, count, and total-byte budgets, while other payloads are prepared only
when selected for a preview. Query changes cancel outstanding requests and
reject stale worker results. Status text reports every candidate or preparation
cap; legacy mode continues to use the existing entry callbacks.

The fixed ceilings are 4,096 picker rows, 4,096 query analysis candidates,
1,024 session text candidates, and 512 prepared text sources. Prepared text is
also capped at 16 MiB per file and 256 MiB per candidate refresh.
