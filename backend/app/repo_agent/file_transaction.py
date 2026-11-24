"""Transaction-scoped file changes with a rollback that cannot destroy user work.

The patch pipeline used to undo itself with ``git reset --hard`` followed by
``git clean -fd``. Those commands know nothing about which changes belong to the
run: in a checkout that already held unrelated modified and untracked files they
would delete every one of them, with no backup and no way back.

This module replaces that with a transaction that only ever touches what it
itself wrote:

* before a file is modified its exact bytes are copied to durable backup storage
  (the same volume the Repo Agent uses, ``REPO_AGENT_BACKUP_ROOT``), and the copy
  is read back and verified — a write is refused if its undo material could not
  be stored;
* every file the transaction writes is recorded, with the hash of the content it
  left behind;
* rollback restores a modified file only when the file still holds exactly what
  the transaction wrote, and deletes a created file only when the same is true.
  If anything changed underneath, that path is reported as a conflict and left
  alone rather than overwritten.

Files the transaction never touched are never touched by its rollback — tracked
modifications, untracked files and the git index included. Nothing here runs a
git command.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import settings
from app.repo_agent.scanner import (
    CRLF,
    LF,
    PathSafetyError,
    content_hash,
    detect_newline_style,
    read_repo_text,
    safe_child_path,
)

# Why a write was refused. These travel back to the caller so a skipped patch can
# explain itself in the pipeline result.
REFUSED_EXISTS = "target_exists"
REFUSED_MISSING = "target_missing"
REFUSED_HASH = "original_changed"
REFUSED_PATH = "unsafe_path"
REFUSED_BACKUP = "backup_failed"


class TransactionError(RuntimeError):
    """Raised when the transaction cannot guarantee it could undo itself."""


@dataclass
class FileChange:
    """One file this transaction wrote."""

    rel_path: str
    created: bool
    backup_path: Optional[str]
    # Hash of what we left in the file. Rollback refuses to act on a path whose
    # current content no longer matches this, because something else wrote it.
    written_hash: str
    original_hash: Optional[str] = None


@dataclass
class RollbackReport:
    restored: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    conflicts: List[Dict[str, str]] = field(default_factory=list)
    failures: List[Dict[str, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts and not self.failures

    def as_dict(self) -> Dict[str, object]:
        return {
            "restored": self.restored,
            "removed": self.removed,
            "conflicts": self.conflicts,
            "failures": self.failures,
            "clean": self.clean,
        }


def _repo_key(root: Path) -> str:
    """A stable, collision-free directory name for one checkout.

    Mirrors the Repo Agent's scheme: two checkouts are often both called "site",
    so the resolved path's digest keeps their backups apart.
    """
    resolved = Path(root).resolve().as_posix()
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^A-Za-z0-9._-]", "-", root.name or "repo").strip("-") or "repo"
    return f"{name}-{digest}"


def _backup_name(rel_path: str) -> str:
    clean = rel_path.replace("\\", "/").strip("/")
    parts = [part for part in clean.split("/") if part]
    if not parts or any(part in {"..", "."} for part in parts):
        raise PathSafetyError(f"Unsafe file path for a backup: {rel_path!r}")
    flat = re.sub(r"[^A-Za-z0-9._-]", "_", "__".join(parts))
    if len(flat) > 120:
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:12]
        flat = f"{flat[:100]}-{digest}"
    return flat


class FileTransaction:
    """Writes files, remembers exactly what it wrote, and can undo only that."""

    def __init__(self, root: Path, run_id: str, backup_root: Optional[Path] = None):
        self.root = Path(root)
        self.run_id = str(run_id)
        self._backup_root = Path(backup_root) if backup_root else Path(settings.REPO_AGENT_BACKUP_ROOT)
        self.changes: List[FileChange] = []

    # -- backup -------------------------------------------------------------

    @property
    def backup_dir(self) -> Path:
        return self._backup_root / _repo_key(self.root) / self.run_id

    def _backup(self, rel_path: str, original_bytes: bytes) -> str:
        """Store the pre-write bytes and prove they are readable.

        Fails closed: if the undo material cannot be written and read back, the
        caller must not write the file.
        """
        directory = self.backup_dir
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / _backup_name(rel_path)
        destination.write_bytes(original_bytes)
        if destination.read_bytes() != original_bytes:
            raise TransactionError(f"Backup for {rel_path} did not read back identically.")
        return str(destination)

    # -- write --------------------------------------------------------------

    def write(
        self,
        rel_path: str,
        content: str,
        *,
        expect_new: bool,
        expected_original_hash: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Write one file under transaction control.

        ``expect_new`` is the patch's own claim. It is checked against the disk,
        never trusted: a "new file" patch whose target already exists is refused
        rather than silently turned into an overwrite, and an "existing file"
        patch whose target is gone is refused too.

        ``expected_original_hash``, when given, must match the file's current
        content or the write is refused — the file changed after the patch was
        prepared.

        Returns ``(ok, detail)``.
        """
        try:
            target = safe_child_path(self.root, rel_path)
        except PathSafetyError as exc:
            return False, f"{REFUSED_PATH}: {exc}"

        exists = target.is_file()
        if expect_new and exists:
            return False, (
                f"{REFUSED_EXISTS}: {rel_path} already exists, but the patch is recorded as "
                "creating a new file. Refusing to overwrite it."
            )
        if not expect_new and not exists:
            return False, (
                f"{REFUSED_MISSING}: {rel_path} does not exist, but the patch expects to update "
                "an existing file."
            )

        original_bytes = b""
        original_hash = None
        newline = LF
        if exists:
            original_bytes = target.read_bytes()
            newline = detect_newline_style(original_bytes)
            current = read_repo_text(target)
            original_hash = content_hash(current)
            if expected_original_hash and original_hash != expected_original_hash:
                return False, (
                    f"{REFUSED_HASH}: {rel_path} has changed since the patch was prepared "
                    "(content hash mismatch). Refusing to overwrite it."
                )
            try:
                backup_path = self._backup(rel_path, original_bytes)
            except (OSError, PathSafetyError, TransactionError) as exc:
                return False, f"{REFUSED_BACKUP}: could not store undo material for {rel_path}: {exc}"
        else:
            backup_path = None

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline=newline)

        self.changes.append(
            FileChange(
                rel_path=rel_path,
                created=not exists,
                backup_path=backup_path,
                written_hash=content_hash(read_repo_text(target)),
                original_hash=original_hash,
            )
        )
        return True, "applied"

    # -- rollback -----------------------------------------------------------

    def rollback(self) -> RollbackReport:
        """Undo only this transaction's own writes.

        A path whose current content no longer matches what this transaction
        left there was changed by someone else afterwards. That is reported as a
        conflict and left untouched — overwriting it would be exactly the data
        loss this class exists to prevent.
        """
        report = RollbackReport()
        for change in reversed(self.changes):
            try:
                target = safe_child_path(self.root, change.rel_path)
            except PathSafetyError as exc:
                report.failures.append({"path": change.rel_path, "reason": str(exc)})
                continue

            if not target.exists():
                if change.created:
                    # Already gone; the outcome we wanted.
                    report.removed.append(change.rel_path)
                else:
                    report.conflicts.append({
                        "path": change.rel_path,
                        "reason": "File was deleted after this run modified it; not restoring.",
                    })
                continue

            current_hash = content_hash(read_repo_text(target))
            if current_hash != change.written_hash:
                report.conflicts.append({
                    "path": change.rel_path,
                    "reason": (
                        "File changed after this run wrote it; left as it is to avoid "
                        "destroying that change."
                    ),
                })
                continue

            if change.created:
                try:
                    target.unlink()
                    report.removed.append(change.rel_path)
                except OSError as exc:
                    report.failures.append({"path": change.rel_path, "reason": str(exc)})
                continue

            if not change.backup_path:
                report.failures.append({
                    "path": change.rel_path,
                    "reason": "No backup was recorded for a modified file; not restoring.",
                })
                continue
            backup = Path(change.backup_path)
            if not backup.is_file():
                report.failures.append({
                    "path": change.rel_path,
                    "reason": f"Backup file is missing ({backup}); not restoring.",
                })
                continue
            try:
                target.write_bytes(backup.read_bytes())
                report.restored.append(change.rel_path)
            except OSError as exc:
                report.failures.append({"path": change.rel_path, "reason": str(exc)})
        return report

    @property
    def written_paths(self) -> List[str]:
        return [change.rel_path for change in self.changes]
