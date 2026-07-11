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
