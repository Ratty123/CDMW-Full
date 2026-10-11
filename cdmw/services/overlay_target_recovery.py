"""Per-target evidence for rollback of a confirmed overlay transaction.

The installation lane excludes cooperating CDMW writers. Hash checks also refuse
observed foreign contents, but cannot exclude an arbitrary writer between a check
and a filesystem operation. Original backup manifests and copies stay immutable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from cdmw.core.atomic_file import atomic_copy_file, atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled


def payload_digest(payload):
    return None if payload is None else hashlib.sha256(payload).hexdigest()


def file_digest(path):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path:
        raise RuntimeError(f"Overlay target has an unexpected link: {path}")
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError(f"Overlay target is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class OverlayTargetRecovery:
    """Record an attempt before each writer, including replace/unlink-then-error."""

    def __init__(self, root, before, *, backup_dir=None, restore_backup=None, stop_event=None):
        self.root = Path(root).resolve()
        self.before = {Path(path).resolve(): digest for path, digest in before.items()}
        self.current = dict(self.before)
        self.backup_dir = Path(backup_dir).resolve() if backup_dir is not None else None
        self.restore_backup = restore_backup
        self.stop_event = stop_event
        self.rows = {}
        self.sources = {}
        self.created_dirs = []
        self.artifacts = {}
        self.directory = None
        self.journal = None
        self.status = "prepared"

    @property
    def recovery_location(self):
        return self.backup_dir or self.directory or self.root

    def validate(self):
        for path, expected in self.current.items():
            if file_digest(path) != expected:
                raise RuntimeError(f"Overlay target changed after preparation: {path}")

    def _mkdir(self, directory):
        missing = []
        parent = directory
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        directory.mkdir(parents=True, exist_ok=True)
        self.created_dirs.extend(reversed(missing))

    def _write_record(self, path, payload):
        atomic_write_bytes(path, payload)
        self.artifacts[path] = payload_digest(payload)

    def _save(self, status):
        self.status = status
        payload = {"format": "cdmw_overlay_target_journal_v1", "status": status,
                   "package_root": str(self.root), "backup_dir": str(self.backup_dir or ""),
                   "originals": [{"target": str(path), "backup_path": str(source),
                                  "sha256": self.before[path]} for path, source in self.sources.items()],
                   "targets": list(self.rows.values())}
        self._write_record(self.journal, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def _prepare(self):
        if self.directory is not None:
            return
        originals = {path: digest for path, digest in self.before.items() if digest is not None}
        if self.backup_dir is not None and self.restore_backup is not None:
            manifest_path = self.backup_dir / "backup_manifest.json"
            if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
                raise RuntimeError(f"The overlay backup manifest is missing or invalid: {manifest_path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in manifest.get("files", ()):
                original = Path(row["original_path"]).resolve()
                source = Path(row["backup_path"]).resolve()
                if (original in self.sources or self.backup_dir not in source.parents
                        or original not in originals or file_digest(source) != originals[original]):
                    raise RuntimeError(f"The overlay backup does not match its original target: {original}")
                self.sources[original] = source
            if set(self.sources) != set(originals):
                raise RuntimeError("The overlay backup did not preserve every original target")
        base = self.backup_dir or self.root / ".cdmw" / "overlay-recovery"
        self.directory = base / ("cdmw-recovery-" + uuid4().hex)
        self._mkdir(self.directory)
        self.journal = self.directory / "mutation-journal.json"
        if not self.sources:
            for index, (original, expected) in enumerate(originals.items()):
                source = self.directory / f"original-{index:04d}.bin"
                atomic_copy_file(original, source)
                if file_digest(source) != expected:
                    raise RuntimeError(f"Overlay target changed while preserving recovery bytes: {original}")
                self.sources[original] = source
                self.artifacts[source] = expected
        self._save("prepared")

    def mutate(self, changes, operation):
        changes = {Path(path).resolve(): after for path, after in changes.items()}
        for path in changes:
            if path not in self.before or file_digest(path) != self.current[path]:
                raise RuntimeError(f"Overlay target changed before its mutation: {path}")
        self._prepare()
        if not self.rows:
            raise_if_cancelled(self.stop_event, 'Overlay operation cancelled before its first mutation.')
        # Recovery preparation can do I/O. Recheck immediately before claiming an attempt.
        for path in changes:
            if file_digest(path) != self.current[path]:
                raise RuntimeError(f"Overlay target changed before its mutation: {path}")
        for path, after in changes.items():
            row = self.rows.setdefault(path, {"target": str(path), "before_sha256": self.before[path],
                                             "attempted": True, "completed": False, "steps": []})
            row.update(after_sha256=after, completed=False)
            row["steps"].append({"before_sha256": self.current[path], "after_sha256": after, "completed": False})
        self._save("applying")
        operation()
        for path, after in changes.items():
            if file_digest(path) != after:
                raise RuntimeError(f"Overlay target does not match its attempted mutation: {path}")
            self.current[path] = after
            self.rows[path]["completed"] = True
            self.rows[path]["steps"][-1]["completed"] = True
        self._save("applying")

    def write(self, path, payload, writer):
        path = Path(path).resolve()
        def publish():
            self._mkdir(path.parent)
            writer(path, payload)
        self.mutate({path: payload_digest(payload)}, publish)

    def unlink(self, path):
        path = Path(path).resolve()
        self.mutate({path: None}, lambda: path.unlink(missing_ok=True))

    def _owned_changes(self):
        changed = {}
        for path, row in self.rows.items():
            current = file_digest(path)
            if current == self.before[path]:
                continue
            if current not in {step["after_sha256"] for step in row["steps"]}:
                raise RuntimeError(f"Unknown contents at {path}; preserve this target for recovery")
            changed[path] = current
        return changed

    def rollback(self):
        if not self.rows:
            self._cleanup()
            return
        try:
            self._save("recovering")
            changed = self._owned_changes()
            existing = [path for path in changed if self.before[path] is not None]
            if existing:
                for path in existing:
                    if file_digest(self.sources[path]) != self.before[path]:
                        raise RuntimeError(f"Recovery copy changed for {path}")
                scope = self.directory / "scoped-restore"
                self._mkdir(scope)
                manifest = {"description": "Verified transaction-owned overlay rollback",
                            "original_backup": str(self.backup_dir or ""),
                            "files": [{"original_path": str(path), "backup_path": str(self.sources[path])}
                                      for path in existing]}
                self._write_record(scope / "backup_manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
                # The full backup is never passed to automatic rollback or rewritten.
                if self._owned_changes() != changed:
                    raise RuntimeError("Overlay targets changed before scoped recovery")
                if self.restore_backup is not None and self.backup_dir is not None:
                    self.restore_backup(scope)
                else:
                    from cdmw.core.archive_patching import restore_archive_patch_backup
                    restore_archive_patch_backup(scope)
                for path in existing:
                    if file_digest(path) != self.before[path]:
                        raise RuntimeError(f"Rollback did not restore {path}")
            for path in reversed(tuple(changed)):
                if self.before[path] is not None:
                    continue
                if file_digest(path) != changed[path]:
                    raise RuntimeError(f"Overlay target changed before rollback cleanup: {path}")
                path.unlink(missing_ok=True)
                if file_digest(path) is not None:
                    raise RuntimeError(f"Rollback did not remove its created target: {path}")
            self._save("rolled_back")
        except BaseException:
            try:
                self._save("recovery_required")
            except OSError:
                pass
            raise
        self._cleanup()

    def committed(self):
        if self.journal is not None:
            self._save("committed")
        self._cleanup()

    def _cleanup(self):
        # Keep evidence beside an external full backup. A successful local-only
        # transaction can discard its own copies, never unknown files beside them.
        if self.backup_dir is None:
            for path, digest in reversed(tuple(self.artifacts.items())):
                try:
                    if file_digest(path) == digest:
                        path.unlink(missing_ok=True)
                except (OSError, RuntimeError):
                    pass
        for directory in reversed(self.created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
