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

Required fields: summary, affected tool/workflow, reproduction steps, expected
result, actual result/error, frequency, game version/platform, mods/manager and the
result of testing without mods. `Unknown`, `None` and `Not tried` are useful answers.
Contact is optional. No GitHub account is required by the reporter.

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
Evidence is inaccessible after 90 days and R2 removes it through the lifecycle rule.
Private issue summaries remain until the maintainer removes them.

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
