# CDMW private reporting test

The source app offers **Help > Report a Problem...** and **More > Report a Problem...**.
This is a private submission test, not an anonymous public intake service.

## Installed test resources

- Worker: `cdmw-reports-test`, on the Workers Free plan.
- Intake: `https://cdmw-reports-test.fredriccarlberg.workers.dev/reports`.
- Health: `https://cdmw-reports-test.fredriccarlberg.workers.dev/health`.
- Private GitHub inbox: `Ratty123/CDMW-Reports`.
- Private Standard R2 bucket: `cdmw-reports-test`, bound as `REPORTS`.
- Object lifecycle: delete `reports/` objects after 90 days.

The Worker has two encrypted secrets: `GITHUB_TOKEN` and `REPORT_TEST_TOKEN`.
The GitHub token is fine-grained, restricted to this one inbox, with Issues read/write
and the required Metadata read permission. The initial token expires October 31,
2026. Rotate it in Cloudflare before that date. Never put it in the desktop app.

The local test access key is in the ignored
`workspace/problem_report_test/access-key.txt`. The local test launcher reads it into
`CDMW_REPORT_TEST_TOKEN` for that CDMW process only. Keep this key out of commits,
screenshots, public builds and shared reports. Starting CDMW normally leaves sending
disabled; collecting a local draft still works.

## Reports and privacy

The five guided steps are Problem, Reproduce, Setup, Evidence and Review. Choose
the tool from the current CDMW tool list, then an affected action/panel. For example,
Mesh Editor offers Cloth, Vertex Parameters, Hair Tools, UV editing and replacement
imports. An Other / not sure route accepts a feature name. Problem type, summary,
reproduction steps, expected/actual result and frequency are required. Input
formats, item prompts and **?** help follow the selected tool/action. Unknown items
have an explicit choice; app/window issues do not require an asset name.

Stalls require wait time and progress/response choices. Setup asks whether game
files/mods are involved; app-only reports skip game questions. Game reports ask
for platform, version (or Unknown), installed-mod state and any prior test without
mods. Installed mods and export/install problems also ask for manager, install
method and relevant mod/output names. A failed export still asks for its target
manager even if no mods are installed; Not installed yet and Not sure are valid
choices. No game-file changes are required to report a problem. If it worked
before, describe recent changes or write `Not sure yet`.
Contact is optional. No GitHub account is required by the reporter.
The pilot's new guidance uses English source wording; translation review is still
needed before a wider rollout.

The collector runs on a separate cancellable worker even if another CDMW tool is
busy. It captures the context at opening, recent log excerpts, up to 40 runtime
events before that time, cache health as metadata-only evidence, selected archive
file existence/size/time, and a bounded game/archive folder listing. It does not
follow symlinks/junctions or descend into backup folders, read game payloads, hash
the whole installation, copy settings, choose an old unrelated crash, or mutate
game files. Folder listings are capped and explicitly identify partial/unavailable
data. Cache health is not proof of an unmodified game installation.

Common credentials and absolute local paths are redacted before draft publication.
Up to three user-selected PNG/JPEG/WebP screenshots are converted to JPEG, resized
to at most 1920 pixels on either side and stripped of metadata. Visible image content
must be reviewed by the user. All textual evidence and screenshots are available in
the review step. The exact uploaded JSON is saved atomically under
`workspace/problem_reports/`; local drafts are not automatically deleted.

The receiver caps each body at 8 MiB, validates required fields and screenshot
format, and refuses to create issues unless the configured inbox is private.
New reports retain the exact reviewed JSON text in storage and downloads; large
integer timestamps cannot be rounded during delivery. Earlier prototype records
retain their original format and accepted receipts.
It creates a private issue containing the human description and an evidence link.
The link grants access to that report only, so do not repost it. Its key is carried
in the URL fragment and then an Authorization header, not a server URL query.
The evidence viewer renders descriptions as text and uses no third-party assets.
Cloudflare still processes network/request metadata as the hosting provider.

Only a matching accepted receipt is shown as success. Retries use the same ID and
payload; R2 conditional writes serialize delivery, and ambiguous GitHub failures
are reconciled against existing issues before creating another. Pending deliveries
can be retried after two minutes. A failed upload keeps the local draft. Edited and
recollected reports get a new ID; do not recollect merely to retry an upload.
**Open draft…** reopens the exact ID and payload after an app restart. It checks
the format, screenshot limits/metadata and redaction before review; altered unsafe
drafts must be recollected. Consent is required again. **Copy receipt** supplies the
reference for follow-up. A server limit shows a countdown; it never triggers an
automatic retry. Screenshots must be selected again if an opened draft is edited
and recollected.
The targeted choices are stored in the existing schema-v1 description fields;
the private receiver and issue summaries accept them without a deployment or
schema migration. Existing drafts retain their exact retry body. Editing an old
draft requires completing the new action/source selections before recollection.
Evidence is inaccessible after 90 days and R2 removes it through the lifecycle rule.
Private issue summaries remain until the maintainer removes them.

## Spam controls in the private pilot

- A valid private test key is required before reading evidence or calling GitHub.
- At most **10 new report admissions per UTC day** across the service, **5 per
  internet connection per UTC day**, and a **two-minute gap** between new reports
  from that connection. Shared networks share this allowance.
- A two-second global gap bounds writes to the admission object. One conditional
  R2 write reserves capacity before report evidence or GitHub issues are created.
  Concurrent requests cannot overrun the cap. Unavailable or corrupt protection
  storage fails closed. Failed deliveries keep their reservation for recovery;
  retries from a previous day must reserve current-day capacity.
- Matching descriptions from the same connection on the same day are rejected even
  with a new ID, changed timestamps or different collected evidence. Exact accepted
  retries return the original receipt and remain available after quota exhaustion.
- Early per-Worker-instance burst limits (40 requests per connection/minute and
  120 total/minute) reduce repeated body reads. These are best-effort; the persistent
  admission limits provide the cross-instance enforcement.

The bounded ledger lives at `reports/_admission-v1.json` in the existing private
bucket and stores only the current UTC day, report IDs, description hashes,
timestamps and daily HMAC network identifiers. Raw IP addresses are not stored in
reports, issues or the ledger. Cloudflare supplies the connection IP; client IDs and
forwarding headers cannot choose the quota key. A new day replaces the ledger's old
entries. The existing `reports/` lifecycle also removes an inactive ledger after
90 days. The Worker uses the existing bucket/secrets; no additional service or paid
upgrade is needed. R2 consistency/conditional writes and its single-key write rate
are described in the [Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)
and [R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

These controls bound report creation and storage; they do not guarantee zero
request costs or prevent an attacker from consuming the day's allowance. VPNs can
change the per-connection identity, while the global cap still applies. Anonymous
public intake needs a real human-verification/moderation flow before release.

## Maintenance and validation

The canonical dependency-free Worker source is `worker.mjs`. Deploy it through the
Cloudflare editor using the **Latest** version, retaining both encrypted secrets and
the `REPORTS` bucket binding. Refresh settings before applying changes; a stale
dashboard version can overwrite newer bindings. No paid Workers plan, custom domain,
Queues, D1, R2 API token or email service is required for this test.

```powershell
node --test tools/problem_report_receiver/worker.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_problem_reporting.py -p no:cacheprovider --basetemp="$env:TEMP\cdmw-problem-report-tests"
```

Before a public rollout, replace the shared private test key with a user-appropriate
verification and abuse-control flow, decide moderation/contact handling, and review
request/storage budgets and retention. Do not embed the test key into a released EXE.
The service has no paid-plan upgrade or hard billing cap; R2 bills usage above its
free allowance. Size limits and private test access reduce usage but do not guarantee
a zero bill. See [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
and [R2 pricing](https://developers.cloudflare.com/r2/pricing/).
