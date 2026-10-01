# CDMW problem reporting

The source app offers **Help > Report a Problem...** and **More > Report a Problem...**.
Public CDMW clients submit through a browser check to a separate private inbox.
No GitHub login, GitHub token or shared submission key is needed in the app.

## Service configuration

- Worker: `cdmw-reports`, on the Workers Free plan.
- Intake: `https://cdmw-reports.cdmw-workbench.workers.dev/reports`.
- Health: `https://cdmw-reports.cdmw-workbench.workers.dev/health`.
- Private GitHub inbox: `Ratty123/CDMW-Reports`.
- Private Standard R2 bucket: `cdmw-reports-test`, bound as `REPORTS`.
- Object lifecycle: delete `reports/` objects after 90 days.

The Worker needs these runtime values:

| Name | Type | Purpose |
| --- | --- | --- |
| `REPORTS` | R2 binding | Existing private `cdmw-reports-test` bucket |
| `GITHUB_TOKEN` | Encrypted secret | Issues read/write in `Ratty123/CDMW-Reports` only |
| `TURNSTILE_SITE_KEY` | Plaintext variable | Public key for the browser widget |
| `TURNSTILE_SECRET_KEY` | Encrypted secret | Server verification and signed submission tickets |
| `PUBLIC_REPORTS` | Plaintext variable, `1` | Enable public clients with browser verification |

Create a Managed Cloudflare Turnstile widget restricted to
`cdmw-reports.cdmw-workbench.workers.dev`. Use its actual keys; known Cloudflare test
keys cannot enable the public receiver. Deploy the canonical Worker and retain the
existing GitHub secret and bucket binding before enabling public submissions.
`/health` must return `configured: true` and `verification: "browser"` before
releasing the client. Missing configuration fails closed and keeps the app's draft.

The GitHub token is fine-grained, restricted to this one inbox, with Issues read/write
and the required Metadata read permission. The current token expires October 1,
2027. Rotate it in Cloudflare before that date. Never put it in the desktop app.

Keep both encrypted secrets out of source, desktop builds, screenshots and reports.
The site key is public; the browser page receives it from the Worker. The desktop
app contains only the service URL and never reads `CDMW_REPORT_TEST_TOKEN`.

For receiver-only legacy pilot tests, leaving `PUBLIC_REPORTS` unset retains the
original `REPORT_TEST_TOKEN` authentication. Public mode ignores that key. The
current desktop client always uses browser verification, so the old local test
launcher is unnecessary. Existing stored reports and draft schema-v1 remain valid.

## Reports and privacy

CDMW Full's source repository is public. Reports go to the separate private
`Ratty123/CDMW-Reports` repository, visible to its maintainer and invited repository
collaborators. A reporter receives a reference, not a link to the private issue.
The app's Review and receipt screens explain these access limits through **?** help.
The public source and support inbox are independent. The receiver's repository name
is fixed and it verifies the inbox is private before creating an issue; changing
its visibility stops delivery rather than exposing new reports in a public issue.

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
Guidance uses English source wording where a reviewed translation is unavailable.

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
Anyone with that complete link can read that one report without a GitHub account;
keep it in the restricted inbox. Its random access key is carried in the URL fragment
and then an Authorization header, not a server URL query. The bare URL only opens
a generic viewer with its Review button disabled; it does not return report data.
Missing, incorrect and expired keys return 404 on download. Pages and downloads
use no-store and noindex headers. These headers do not replace access control.
The evidence viewer renders descriptions as text and uses no third-party assets.
Cloudflare still processes network/request metadata as the hosting provider.

After review and consent, **Send report** opens the default browser. Only the report
ID and SHA-256 of its exact bytes are sent before the check. Completing Turnstile
lets CDMW send the already-reviewed report automatically; the browser never receives
the report text or screenshots. **Open browser** reopens the current check.
Once verified, the browser keeps its success message even if the completed
Turnstile token later expires.
**Cancel**, editing or closing invalidates the local request and stops polling;
the saved draft remains. Verification expires after ten minutes, and a changed
internet connection requires starting a fresh check. The app never follows network
redirects or forwards verification credentials to another address.

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

## Spam controls

- A live Turnstile check is validated on the server against its hostname, action,
  challenge nonce and timestamp. A signed ten-minute ticket is tied to one report
  ID, its exact body hash and the app's internet connection. Another body or report
  cannot reuse it. The ticket, site key and legacy test key cannot read evidence.
- **100 new report admissions per UTC day** across the public service, **5 per
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
- Browser verification has separate persistent limits of **500 approvals/day** and
  **20 per connection/day**, with a two-second global reservation gap. Starting a
  check is stateless; it does not write storage or call GitHub. Successful approval
  records contain only ticket hashes, report IDs and expiry times, and are unusable
  after ten minutes. Provider retries reuse a validation key only for the same token.
- Early per-Worker-instance burst limits (90 requests per connection/minute and
  600 total/minute) reduce repeated body reads. These are best-effort; the persistent
  admission limits provide the cross-instance enforcement.

The bounded ledger lives at `reports/_admission-v1.json` in the existing private
bucket. `reports/_verification-admission-v1.json` holds the approval ledger, and
`reports/_verification/` holds approval records. Ledgers store the current UTC day,
report IDs or challenge nonces, description hashes,
timestamps and daily HMAC network identifiers. Raw IP addresses are not stored in
reports, issues or the ledger. Cloudflare supplies the connection IP; client IDs and
forwarding headers cannot choose the quota key. A new day replaces the ledger's old
entries. The existing `reports/` lifecycle also removes an inactive ledger after
90 days. Expired approval records also fall under this lifecycle. R2 consistency,
conditional writes and its single-key write rate
are described in the [Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)
and [R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

Legacy receiver-only private mode retains its 10 report/day and 40/120 burst limits.

These controls bound report creation and storage; they do not guarantee zero
request costs or prevent an attacker from consuming the day's allowance. VPNs can
change the per-connection identity, while the global cap still applies.
Maintainer review is still needed; human verification cannot prevent all abuse.

## Maintenance and validation

The canonical dependency-free Worker source is `worker.mjs`. Deploy it through the
Cloudflare editor using the **Latest** version, retaining encrypted secrets and
the `REPORTS` bucket binding. Refresh settings before applying changes; a stale
dashboard version can overwrite newer bindings. No paid Workers plan, custom domain,
Queues, D1, R2 API token or email service is required for this setup.
The account's `workers.dev` subdomain is `cdmw-workbench`. If it is renamed again,
update the app endpoint and existing issue evidence links; the old hostname stops
routing. Changing the hostname does not change evidence keys or report contents.

```powershell
node --test tools/problem_report_receiver/worker.test.mjs
.\.venv\Scripts\python.exe -m pytest tests/test_problem_reporting.py -p no:cacheprovider --basetemp="$env:TEMP\cdmw-problem-report-tests"
```

Before releasing the client, verify the live browser-to-app flow and private inbox
delivery with a synthetic report. Never test with real game payloads or post evidence
to the public source repository. Review request/storage budgets, retention and
translations. Do not embed any service secret into a released EXE.
The service has no paid-plan upgrade or hard billing cap; R2 bills usage above its
free allowance. Size limits, verification and admission caps reduce usage but do not
guarantee a zero bill. See [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
and [R2 pricing](https://developers.cloudflare.com/r2/pricing/).
