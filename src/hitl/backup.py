"""Backup and restore audit trails.

Simple file-based backup: copy JSONL files to a timestamped backup directory.
Restore verifies the chain integrity before accepting. Archive moves old records
(>N days) to a separate location.

RTO: < 1 minute (restore is just file copy + verification)
RPO: daily (configurable via cron)
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hitl.audit import verify_chain
from hitl.logging import log_event


def backup(audit_dir: Path, backup_root: Path) -> Path:
    """Backup audit trail to timestamped directory.

    Returns the path of the created backup directory.
    Raises if audit_dir does not exist or is not readable.
    """
    if not audit_dir.exists():
        raise ValueError(f"audit directory does not exist: {audit_dir}")

    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    for jsonl_file in sorted(audit_dir.glob("*.jsonl")):
        shutil.copy2(jsonl_file, backup_dir / jsonl_file.name)
        files_copied += 1

    log_event("audit_backup_completed", backup_dir=str(backup_dir), files=files_copied)
    return backup_dir


def restore(backup_dir: Path, audit_dir: Path, verify: bool = True) -> int:
    """Restore audit trail from a backup.

    Overwrites files in audit_dir with those from backup_dir. Verifies the
    chain integrity after restore if `verify=True`.

    Returns the number of files restored.
    Raises ValueError if backup_dir does not exist or verify fails.
    """
    if not backup_dir.exists():
        raise ValueError(f"backup directory does not exist: {backup_dir}")

    audit_dir.mkdir(parents=True, exist_ok=True)
    files_restored = 0

    for backup_file in sorted(backup_dir.glob("*.jsonl")):
        shutil.copy2(backup_file, audit_dir / backup_file.name)
        files_restored += 1

    if verify:
        problems = verify_chain(audit_dir)
        if problems:
            raise ValueError(
                f"Restored audit trail failed integrity check: {len(problems)} problem(s)"
            )

    log_event("audit_restore_completed", backup_dir=str(backup_dir), files=files_restored)
    return files_restored


def archive(audit_dir: Path, archive_dir: Path, older_than_days: int = 180) -> int:
    """Move old audit files to an archive directory.

    Only files whose name (JSONL date prefix) is older than older_than_days are
    moved. JSONL filenames are expected to start with YYYY-MM-DD.

    Returns the number of files archived.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    archive_dir.mkdir(parents=True, exist_ok=True)

    files_archived = 0
    for jsonl_file in sorted(audit_dir.glob("*.jsonl")):
        # Parse date from filename (format: YYYY-MM-DD-...)
        try:
            date_part = jsonl_file.stem.split("-")[:3]
            if len(date_part) == 3:
                file_date_str = "-".join(date_part)
                file_date = datetime.fromisoformat(file_date_str).replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    shutil.move(str(jsonl_file), archive_dir / jsonl_file.name)
                    files_archived += 1
        except (ValueError, IndexError):
            # Filename doesn't match expected format; leave it alone
            pass

    if files_archived > 0:
        log_event("audit_archive_completed", archive_dir=str(archive_dir), files=files_archived)

    return files_archived
