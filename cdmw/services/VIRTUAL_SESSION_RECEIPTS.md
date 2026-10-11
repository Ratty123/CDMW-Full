# Virtual session receipts

## Supported behavior and evidence boundary

Experimental virtual launches record their prepared proposal, verified save-backup
facts, host startup, reported runtime transitions and terminal file observations.
These are local observations. They do not establish a save producer, a successful
game save, runtime activation, save ancestry, inherited requirements or migration
safety. Public game redirection remains gated by the existing runtime policy.

The production path is virtual_loader_runtime.py through
virtual_loader_receipts.py. Pure validation and inspection live in
cdmw/domain/virtual_session_receipt.py. Existing profile, native session,
save-backup and portable package wire formats are unchanged. Optional trailing
dataclass fields carry receipts and diagnostics without changing legacy positional
callers. A starting status's detail remains its exact native session token.

## Receipt format

The closed format is **cdmw_virtual_session_receipt_v1**. Every record has a
SHA-256 identity over canonical UTF-8 JSON excluding its own identity field.
Stored bytes include that identity. Decoding validates the full record and
returns an immutable byte-backed object; callers receive fresh dictionaries.

| Part | Recorded facts |
| --- | --- |
| Record | Attempt UUID, sequence, previous receipt identity, UTC capture time and event |
| Proposed context | Profile and generation, virtual/physical package content and binding hashes, compiler and compilation, executable/build, bootstrap/loader/host and source/underlay identities |
| Backup | Pending, verified, unknown or failed association; owned backup UUID, exact manifest and selected-set hashes when observed |
| Selected files | Hashed canonical relative names, sizes and byte hashes; explicit missing members and read errors |
| Slot knowledge | Nullable layout identity and explicit membership completeness, independent of complete selected-file observation |
| Process | Expected session token, locally started host PID, reported game PID/state and separately nullable observed birth/image/session evidence |
| Outcomes | Reported readiness, terminal state and operator save-attempt outcome as separate fields |
| Provenance | Bounded evidence kind, optional evidence hash, details, diagnostics and adverse indicators |

Events are begin, backup-verified, launch-started, runtime-status, terminal, failed,
interrupted and operator-capture. The sequence establishes observation order;
UTC timestamps describe when observations were recorded. A predecessor is another
receipt, never a parent save.

Each receipt is limited to 4 MiB, each attempt to 512 records and 32 MiB, and each
file observation to 4,096 members and 4 GiB. Metadata and diagnostics have separate
closed-field and length limits. Record inspection rejects unsupported versions,
duplicate JSON keys, changed canonical identity and malformed fingerprints.
Owned-storage chain reads and appends additionally reject incomplete numbering,
unknown directory entries and linked storage. The file-only CLI validates one
record; it does not establish that the record's predecessor chain is available or
complete.

Files are published under
.cdmw/virtual-loader/session-receipts/<attempt UUID>/<sequence>.json.
A complete temporary file is flushed and published exclusively, then read back.
An existing record is never replaced. Parallel appenders resolve exclusive-name
collisions against a newly read chain. No history collection is performed.
The status observer does not acquire the installation lane, which the native host
can retain while the game is running.

Hashes detect content changes relative to retained identities; they do not
authenticate whoever supplied a receipt. Copying or resealing a receipt cannot
grant producer or save-admission authority.

## Lifecycle and truthful outcomes

1. After the existing readiness and profile checks, preparation records its
   proposed context and allocates an attempt token. The host identity is initially
   unknown in this observation; the actual launch path supplies its verified hash.
2. The existing backup service verifies exact copies and live input fingerprints,
   then publishes its unchanged immutable backup manifest. Receipt capture records
   the returned verified file facts without repeating the full save copy.
3. Already committed backup facts are recorded without a late cancellation point.
   Later preparation cancellation retains an interrupted attempt and its verified
   backup. If receipt storage failed, the association remains unknown instead of
   falsely reporting that a committed backup failed.
4. The existing reviewed launch rechecks profile, package, runtime and backup
   guards. After host creation, receipt errors are diagnostics on a starting
   result. Late cancellation cannot erase that result or imply the host was undone.
5. A reused review receives a new token once an earlier launch artifact or receipt
   has consumed its attempt. This also covers successful host creation followed by
   failed receipt publication. Earlier manifests and receipts remain intact.
6. Status capture records state changes, not every progress update. Readiness,
   reported PIDs and process existence remain observations. The current status
   API does not verify game process birth, image or session identity, so those
   proof fields remain null even if untrusted status JSON supplies them.
7. At a terminal observation, a worker hashes the selected files and other bounded
   inventory members. Reads are cancellable, checked twice per file and compared
   with before/after identity and inventory observations. This is not an atomic
   game save or a save-finalization witness.

The selected set initially contains all files from the verified backup. This
does not claim those files form complete game slots. A missing terminal event,
app shutdown, changed backup metadata, unavailable copy, changed configured save
root or interrupted observation leaves explicit gaps. No later poll fabricates
a missed game event.

Receipt lookup accepts only an owned backup ID and its pinned manifest. It checks
the installation, proposal and current configured save root before observing any
terminal files. Transferred receipts do not authorize arbitrary paths or a search
for missing saves. Backup association records verification at publication time;
it is not a promise that retained copies can never be changed externally.

The page shows receipt paths and preparation/launch/status diagnostics in a
bounded read-only pane. It keeps the real session status and token unchanged.
Root changes and close cancel terminal reads and suppress stale queued results.

## Inspection and experiment workflow

Run the file-only inspection path:

~~~powershell
.\.venv\Scripts\python.exe scripts\capture_virtual_save_evidence.py inspect-receipt 'C:\review\receipt.json'
~~~

Inspection reports the proposed context and backup separately from produced
context, and classifies file effects separately from reported save outcomes.
An incomplete or unobserved selected set has no complete selected-set identity.
It calls the existing data-only lineage policy without a witness or verifier.
Known differences between a supplied target proposal and the recorded proposal
are diagnostics about proposals, not conclusions about a save's producing context.

The concrete copied-save preparation, six-stage capture commands, original
recovery procedure and post-attempt retention contract are documented in
cdmw/ui/new_item/VIRTUAL_LOADER.md. The prepare-experiment command requires explicit
disposable copies, selected relative members and a provider UUID. The retain-attempt
command preserves the actual absent_saved input, including missing or partial
members. Restoring the original recovery copy ends that experiment branch; it
cannot substitute for testing the post-attempt save with the provider restored.

## Focused implementation validation

Owning tests cover:

- Strict receipt/schema/identity bounds, immutable copies, incomplete file sets,
  forged trust fields, chain gaps and transferred receipts.
- Actual backup, reviewed launch and terminal status services on owned fixtures.
- Failure and cancellation before publication, after verified backup and after
  host creation; retries preserve prior attempts and native manifests.
- Changed, unchanged, partially changed, missing and unreadable selected files,
  unexpected other-file changes and unavailable terminal evidence.
- Exclusive publication, concurrent appenders, changed storage, file limits,
  process-report mismatches and existing runtime refusal causes.
- Actual queued UI delivery, receipt diagnostics, late cancellation and stale
  close/root results.
- Actual protocol/capture/retention/inspection CLI paths and both restored-input
  continuity checks.

This is source and fixture evidence. The controlled absent-provider game trial,
visible texture trials, complete slot-layout adapters and a production trusted
save-commit observer remain pending. No receipt clears unknown ancestry, migrates
a save, reuses retired IDs or permits recovery material to be collected.
