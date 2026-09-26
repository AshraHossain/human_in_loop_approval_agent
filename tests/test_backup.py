"""Backup and restore audit trails."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hitl.backup import archive, backup, restore
from hitl.cli import main


# --- backup ---------------------------------------------------------------


def test_backup_creates_timestamped_directory(tmp_path):
    """Backup creates a YYYYMMDD_HHMMSS subdirectory."""
    audit_dir = tmp_path / "audit"
    backup_root = tmp_path / "backups"

    audit_dir.mkdir()
    (audit_dir / "2024-01-15-abc123.jsonl").write_text('{"request_id":"r1"}\n')
    (audit_dir / "2024-01-16-def456.jsonl").write_text('{"request_id":"r2"}\n')

    backup_dir = backup(audit_dir, backup_root)

    assert backup_dir.parent == backup_root
    assert (backup_dir / "2024-01-15-abc123.jsonl").exists()
    assert (backup_dir / "2024-01-16-def456.jsonl").exists()


def test_backup_fails_if_audit_dir_missing(tmp_path):
    """Backup raises if audit_dir does not exist."""
    missing = tmp_path / "nonexistent"
    backup_root = tmp_path / "backups"

    with pytest.raises(ValueError, match="does not exist"):
        backup(missing, backup_root)


def test_backup_creates_backup_root_if_missing(tmp_path):
    """Backup creates the backup_root if needed."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "test.jsonl").write_text('{}')

    backup_root = tmp_path / "backups"
    assert not backup_root.exists()

    backup(audit_dir, backup_root)

    assert backup_root.exists()


def test_backup_returns_backup_dir_path(tmp_path):
    """Backup returns the path it created."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "test.jsonl").write_text('{}')

    backup_root = tmp_path / "backups"
    backup_dir = backup(audit_dir, backup_root)

    assert backup_dir.is_dir()
    assert backup_dir.parent == backup_root


# --- restore ---------------------------------------------------------------


def test_restore_copies_files_back(tmp_path):
    """Restore copies audit files from backup to audit_dir."""
    audit_dir = tmp_path / "audit"
    backup_dir = tmp_path / "backup"

    audit_dir.mkdir()
    backup_dir.mkdir()
    (backup_dir / "test.jsonl").write_text('{"a":1}\n')

    # Audit dir starts empty
    assert len(list(audit_dir.glob("*.jsonl"))) == 0

    count = restore(backup_dir, audit_dir, verify=False)

    assert count == 1
    assert (audit_dir / "test.jsonl").read_text() == '{"a":1}\n'


def test_restore_verifies_chain_by_default(tmp_path):
    """Restore verifies chain integrity after restore."""
    from hitl.cli import main

    audit_dir = tmp_path / "audit"
    backup_dir = tmp_path / "backup"

    audit_dir.mkdir()
    backup_dir.mkdir()

    # Create a minimal valid audit record in the backup
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])

    # Copy from audit to backup
    for f in audit_dir.glob("*.jsonl"):
        import shutil
        shutil.copy2(f, backup_dir / f.name)

    # Clear audit and restore
    for f in audit_dir.glob("*.jsonl"):
        f.unlink()

    count = restore(backup_dir, audit_dir, verify=True)
    assert count > 0


def test_restore_fails_if_backup_dir_missing(tmp_path):
    """Restore raises if backup_dir does not exist."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    missing = tmp_path / "missing_backup"

    with pytest.raises(ValueError, match="does not exist"):
        restore(missing, audit_dir)


def test_restore_creates_audit_dir_if_missing(tmp_path):
    """Restore creates audit_dir if needed."""
    backup_dir = tmp_path / "backup"
    audit_dir = tmp_path / "audit"

    backup_dir.mkdir()
    (backup_dir / "test.jsonl").write_text('{}')

    assert not audit_dir.exists()

    restore(backup_dir, audit_dir, verify=False)

    assert audit_dir.exists()


# --- archive ---------------------------------------------------------------


def test_archive_moves_old_files(tmp_path):
    """Archive moves files older than the threshold."""
    audit_dir = tmp_path / "audit"
    archive_dir = tmp_path / "archive"

    audit_dir.mkdir()

    # File from 200 days ago
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).date()
    (audit_dir / f"{old_date}-old-record.jsonl").write_text('{"old":"record"}')

    # File from today
    today = datetime.now(timezone.utc).date()
    (audit_dir / f"{today}-new-record.jsonl").write_text('{"new":"record"}')

    count = archive(audit_dir, archive_dir, older_than_days=180)

    # Only the old file should have been moved
    assert count == 1
    assert (archive_dir / f"{old_date}-old-record.jsonl").exists()
    assert (audit_dir / f"{today}-new-record.jsonl").exists()
    assert not (audit_dir / f"{old_date}-old-record.jsonl").exists()


def test_archive_creates_archive_dir_if_missing(tmp_path):
    """Archive creates the archive_dir if needed."""
    audit_dir = tmp_path / "audit"
    archive_dir = tmp_path / "archive"

    audit_dir.mkdir()
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).date()
    (audit_dir / f"{old_date}-old.jsonl").write_text('{}')

    assert not archive_dir.exists()

    archive(audit_dir, archive_dir, older_than_days=180)

    assert archive_dir.exists()


def test_archive_skips_unparseable_filenames(tmp_path):
    """Archive ignores files that don't match the expected date format."""
    audit_dir = tmp_path / "audit"
    archive_dir = tmp_path / "archive"

    audit_dir.mkdir()

    # Create files with various formats
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).date()
    (audit_dir / f"{old_date}-valid.jsonl").write_text('{}')
    (audit_dir / "no-date-prefix.jsonl").write_text('{}')  # No date, won't be moved

    count = archive(audit_dir, archive_dir, older_than_days=180)

    # Only the dated file should have been moved
    assert count == 1
    assert (archive_dir / f"{old_date}-valid.jsonl").exists()
    assert (audit_dir / "no-date-prefix.jsonl").exists()


def test_archive_respects_threshold(tmp_path):
    """Archive only moves files older than the configured threshold."""
    audit_dir = tmp_path / "audit"
    archive_dir = tmp_path / "archive"

    audit_dir.mkdir()

    # File from 100 days ago
    recent = (datetime.now(timezone.utc) - timedelta(days=100)).date()
    (audit_dir / f"{recent}-recent.jsonl").write_text('{}')

    # File from 200 days ago
    old = (datetime.now(timezone.utc) - timedelta(days=200)).date()
    (audit_dir / f"{old}-old.jsonl").write_text('{}')

    # Use 180 day threshold
    count = archive(audit_dir, archive_dir, older_than_days=180)

    # Only the 200-day-old file should move
    assert count == 1
    assert (archive_dir / f"{old}-old.jsonl").exists()
    assert (audit_dir / f"{recent}-recent.jsonl").exists()


# --- CLI integration -------------------------------------------------------


def test_backup_command(tmp_path):
    """CLI backup command creates a backup."""
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])

    backup_root = tmp_path / "backups"
    main(["--home", str(tmp_path), "backup", "--to", str(backup_root)])

    # Should have created a timestamped subdirectory with files
    backups = list(backup_root.glob("*"))
    assert len(backups) == 1
    assert len(list(backups[0].glob("*.jsonl"))) > 0


def test_restore_command(tmp_path):
    """CLI restore command restores a backup."""
    # Create an audit trail
    main(["--home", str(tmp_path), "submit", "transition P-1 to Done", "--seed", "P-1=To Do"])

    # Back it up
    backup_root = tmp_path / "backups"
    main(["--home", str(tmp_path), "backup", "--to", str(backup_root)])

    # Clear the audit trail
    audit_dir = tmp_path / "audit"
    for f in audit_dir.glob("*.jsonl"):
        f.unlink()

    assert len(list(audit_dir.glob("*.jsonl"))) == 0

    # Restore from the backup
    backup_subdir = list(backup_root.glob("*"))[0]
    main(["--home", str(tmp_path), "restore", "--from", str(backup_subdir)])

    # Files should be back
    assert len(list(audit_dir.glob("*.jsonl"))) > 0


def test_archive_command(tmp_path):
    """CLI archive command archives old records."""
    # Create an old audit record by manually writing it
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).date()
    (audit_dir / f"{old_date}-old.jsonl").write_text('{"request_id":"r1"}\n')

    archive_dir = tmp_path / "archive"
    main(["--home", str(tmp_path), "archive", "--to", str(archive_dir), "--older-than", "180"])

    assert (archive_dir / f"{old_date}-old.jsonl").exists()
    assert not (audit_dir / f"{old_date}-old.jsonl").exists()
