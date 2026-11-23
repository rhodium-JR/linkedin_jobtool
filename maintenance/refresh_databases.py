"""Back up and recreate the project's SQLite databases."""
from datetime import datetime
import shutil
import sqlite3
from pathlib import Path
import sys

# Add the project root when this file runs from its subfolder.
PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import ALL_JOBS_DB, JOBS_DB, HISTORY_DIR, OUTPUT_DIR
from database import initialise_databases

# Map menu choices to the databases they affect.
DATABASES = {
    "all_jobs.db": ALL_JOBS_DB,
    "jobs.db": JOBS_DB,
}

# Refuse refresh when another process holds a write transaction.
def ensure_database_available(database_path):
    if not database_path.exists():
        return
    connection = sqlite3.connect(str(database_path), timeout=2)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    except sqlite3.OperationalError as error:
        raise RuntimeError(
            f"Database is busy: {database_path.name}. Close the scraper or database viewer."
        ) from error
    finally:
        connection.close()

# Back up one SQLite database using SQLite's online backup API.
def backup_database(source_path, backup_path):
    if not source_path.exists():
        return False
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(source_path), timeout=30)
    destination = sqlite3.connect(str(backup_path))
    try:
        source.execute("PRAGMA wal_checkpoint(FULL)")
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    finally:
        destination.close()
        source.close()
    return True

# Remove SQLite sidecar files after a verified backup.
def remove_database_files(database_path):
    for path in (
        database_path,
        Path(str(database_path) + "-wal"),
        Path(str(database_path) + "-shm"),
    ):
        if path.exists():
            path.unlink()

# Back up selected databases before recreating them.
def refresh(selected_names, recreate=True):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_dir = HISTORY_DIR / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    backed_up = []

    # Verify every existing database before removing any.
    for name in selected_names:
        source = DATABASES[name]
        ensure_database_available(source)
        if source.exists():
            destination = archive_dir / name
            backup_database(source, destination)
            backed_up.append(destination)

    # Delete only after every backup has passed integrity checks.
    if recreate:
        for name in selected_names:
            remove_database_files(DATABASES[name])
        initialise_databases()

    print("\nDatabase maintenance complete.")
    if backed_up:
        print(f"Verified backups: {archive_dir}")
        for path in backed_up:
            print(f"  - {path.name}")
    else:
        print("No existing databases needed backing up.")
    if recreate:
        print("Fresh database schemas are ready.")

# Display the maintenance menu and request confirmation.
def main():
    print("\nDATABASE MAINTENANCE")
    print("1 - Full refresh (both databases)")
    print("2 - Shortlist refresh (jobs.db only)")
    print("3 - Backup only (both databases)")
    print("0 - Cancel")
    choice = input("\nSelect an option: ").strip()

    if choice == "1":
        names = list(DATABASES)
        action = "back up and recreate both databases"
        recreate = True
    elif choice == "2":
        names = ["jobs.db"]
        action = "back up and recreate jobs.db only"
        recreate = True
    elif choice == "3":
        names = list(DATABASES)
        action = "back up both databases without deleting them"
        recreate = False
    elif choice == "0":
        print("Cancelled; no changes made.")
        return
    else:
        print("Invalid option; no changes made.")
        return

    print(f"\nYou are about to {action}.")
    confirmation = input("Type YES to continue: ").strip()
    if confirmation != "YES":
        print("Cancelled; no changes made.")
        return
    refresh(names, recreate=recreate)

if __name__ == "__main__":
    main()
