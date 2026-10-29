"""Shared recovery guidance for diagnostic messages and external failures."""

MESSAGE_REFERENCE_INTRO = """
<p>The message index includes errors without a code, validation refusals, warnings and native/helper diagnostics. Search a distinctive part of the message as well as its code. Braces and percent placeholders represent runtime values such as a path, number or upstream error; they are not text you must type.</p>
<p>Each group gives likely causes and recovery steps, followed by the messages and their owning source files. A cause is a starting point, not a diagnosis proved by the wording alone. Follow a more specific instruction in the actual error. Repeated messages can come from different tools.</p>
<p>The source audit includes application Python, feature tools and first-party Rust, C++ and .NET helpers. Unit tests, development harnesses, generated files and vendored libraries are excluded. A source entry can belong to an optional helper or a guarded path that your installed release does not use.</p>
<p>Some failures contain only an exception, operating-system message, provider response or subprocess output supplied at runtime. Their possible text is not a finite CDMW list. The external-error guidance explains how to identify the source and retain the details needed for diagnosis.</p>
"""

# These are shared explanations, not automatic repairs. No advice changes game
# archives, bypasses validation or claims a successful retry proves game safety.
RECOVERY_GUIDANCE = {
    "missing": ("Missing files or resources", "A source file or directory no longer exists. Check the configured path and rescan."),
    "helper": ("Missing or incompatible helpers", "A helper, library or required runtime is missing, blocked or from a different build. Use a complete matching CDMW distribution and check the reported executable path. Keep the helper's error output; do not download individual DLLs from unrelated sites."),
    "permission": ("Access denied", "The operating system denied file access. Check folder permissions and file protection."),
    "locked": ("Files in use", "Another process holds a conflicting file lock. Close the competing operation and retry."),
    "space": ("Disk space and memory", "The operation could not obtain enough disk space or memory. Check the output and temporary drives, close unnecessary workloads and reduce the input size. Preserve recovery files; increasing a safety limit is not a fix."),
    "timeout": ("Timeouts", "The backend operation exceeded its time limit. Inspect the last stage and retry once the cause is addressed."),
    "cancelled": ("Cancelled operations", "The operation was cancelled or its owner closed. A cancellation is not proof of corrupt input. Keep the last accepted work and inspect any output or recovery report before starting a new attempt."),
    "unsupported": ("Unsupported operations", "The backend does not support the requested operation or input. Use a supported route."),
    "format": ("Invalid or incomplete file data", "The reader found an unexpected header, encoding, layout or incomplete payload. Confirm the file type and matching companion files, then retry an unchanged original or re-export with supported settings. A parse error alone does not prove the game installation is corrupt."),
    "input": ("Invalid values or selections", "A required value, selection or relationship does not satisfy the tool's rules. Correct the named field, range, item or dependency and rebuild the plan or validation report. Keep identifiers from the matching source data instead of guessing replacements."),
    "limits": ("Resource and format limits", "The input exceeds a size, count, index or resource limit. Reduce the affected selection or export in supported parts. A format limit may require a different workflow; do not remove the guard or force a truncated result."),
    "empty": ("Nothing available to process", "The operation has no usable input, selection, matching result or pending change. Check filters and paths, load the required data and select the intended content. Empty output is not evidence that an export or installation succeeded."),
    "conflict": ("Existing or conflicting output", "The destination already exists or conflicts with another package or operation. Inspect it and choose a separate output name or use the tool's explicit replacement flow. Do not delete unknown files or combine overlapping mods to suppress the warning."),
    "stale": ("Changed or stale state", "The source, selection, revision or result no longer matches the active operation. Refresh from the current source and repeat the selection or validation. Preserve accepted work; an old response may be deliberately ignored rather than applied to newer edits."),
    "integrity": ("Integrity and identity checks", "The bytes, hash, signature or source identity do not match the expected input or output. Keep the originals and failed report, restore matching companions and stop repeated writes. Do not edit a manifest or receipt to hide the mismatch."),
    "recovery": ("Safety and recovery refusals", "The operation cannot prove that a write, rollback or restore is safe. Keep backups and receipts, inspect the recovery report and follow the documented restore flow for that exact target. Do not bypass confirmation or remove recovery material."),
    "gpu": ("Graphics and rendering failures", "The renderer could not create or use a device, surface, shader or texture resource. Preserve accepted work, check the reported graphics backend and supported driver, and reopen the preview. Report repeated device loss or crashes with the native log; a blank preview does not prove the asset is empty."),
    "network": ("Network and provider failures", "A remote service could not be reached or returned an unsuccessful response. Check connectivity, the configured service and its status, then retry after any stated delay. Keep the HTTP status and response detail, but remove credentials before sharing a report."),
    "authentication": ("Credentials, permissions and quotas", "The external service rejected credentials, access or usage limits. Check the selected provider, account permission and available quota. Never include API keys, authorization headers or private tokens in a report."),
    "configuration": ("Settings, schemas and versions", "The settings, document schema or protocol does not match what this build expects. Use matching application and helper versions, check the named setting and reopen or re-export with the supported format. Preserve the original configuration before changing it."),
    "write": ("Output and publication failures", "Writing, validating or publishing the output failed. Inspect the destination, free space, permissions and complete report. A staged file is not necessarily a completed output; verify the final path before retrying, replacing or installing anything."),
    "internal": ("Unexpected or forwarded failures", "The component stopped or forwarded an error whose exact cause is in the accompanying detail. Record the action, full message, application/helper version and reproducible input. Reopen the last accepted work; report repeated failures instead of forcing the operation."),
}

MESSAGE_AREAS = {
    "archive": "Archive error messages",
    "formats": "File-format error messages",
    "mesh": "Mesh and editing error messages",
    "materials": "Material error messages",
    "textures": "Texture error messages",
    "items": "Item authoring error messages",
    "placement": "Placement and animation error messages",
    "packages": "Package and recovery error messages",
    "independent": "Independent item and loader error messages",
    "translations": "Translation and provider error messages",
    "settings": "Settings and startup error messages",
    "capture": "Capture and research error messages",
    "other": "Other application error messages",
}

EXTERNAL_ERROR_GUIDE = """
<p>Keep the complete message, tool name, operation and error namespace. A Windows error, HTTP status, HRESULT, native status and process exit number are different systems. The same decimal number can mean different things in each; exit code 1 or 2 alone does not identify a CDMW failure.</p>
<p>For Windows file errors, 2 or 3 usually means a missing file or path; 5 means access was denied; 32 or 33 indicates a sharing or locking conflict; 112 indicates a full disk; 123 or 206 points to an invalid or excessively long name. Check the path and action reported by the failing component. These meanings apply to Win32 error numbers, not arbitrary process exit codes.</p>
<p>Windows loader errors 126, 127 or 193 can indicate a missing dependency, a missing entry point or an incompatible executable. The named program can exist while one of its dependencies is missing. Restore the complete matching distribution and inspect the helper's startup detail.</p>
<p>A process ending with NTSTATUS 0xC0000005 suffered an access violation; 0xC000007B indicates an invalid image format; 0xC0000135 indicates a missing DLL; 0xC0000142 indicates DLL initialization failure. A log may show the same 32-bit value as a signed decimal number. Preserve the crash log and version; these values identify a failure class, not the faulty file or a guaranteed remedy.</p>
<p>For NCNN, chaiNNer, Blender, OpenImageIO, audio converters and other external tools, retain the executable version, command stage, exit status and standard error. Check the selected model, input format, output path and tool-specific requirements. CDMW cannot assign a universal meaning to every message produced by another program.</p>
<p>For HTTP or AI-provider failures, retain the status and provider error type. Authentication failures, rate limits, unavailable models, malformed requests and server failures need different remedies. Follow the provider's current documentation and retry instructions. Do not publish credentials or assume repeated retries will fix an invalid request.</p>
<p>When no code or useful detail is shown, use Report a Problem and attach the reviewed diagnostic report. Include what you clicked, the affected input type, the expected result and whether an unchanged original also fails. The absence of a named code does not mean that the operation succeeded.</p>
<p><a href="https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-">Windows system error reference</a> · <a href="https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55">Windows NTSTATUS reference</a></p>
"""
