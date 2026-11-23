"""Shared SQLite schemas and database helpers."""
from contextlib import contextmanager
import sqlite3
from config import ALL_JOBS_DB, JOBS_DB, OUTPUT_DIR

# Define all scraped-job and screening columns.
JOB_COLUMNS = """
    link TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    country TEXT,
    date_text TEXT,
    linkedin_id TEXT UNIQUE,
    company_link TEXT,
    insights TEXT,
    description TEXT,
    language TEXT,
    LangDet TEXT,
    search_url TEXT,
    first_seen TEXT,
    last_seen TEXT,
    description_hash TEXT,
    rejected TEXT DEFAULT 'N',
    rejection_point TEXT,
    rejection_reason TEXT,
    filter_reason TEXT,
    ai_summary TEXT,
    ai_job_type TEXT,
    ai_phd_requirement TEXT,
    ai_subject_area TEXT,
    ai_seniority TEXT,
    ai_experience_years REAL,
    ai_working_language TEXT,
    ai_decision TEXT,
    ai_bin_reason TEXT,
    ai_reason TEXT,
    processing_status TEXT DEFAULT 'SCRAPED',
    last_processed TEXT,
    processing_error TEXT,
    prompted TEXT DEFAULT 'N'
"""

# Define matching fields stored only for accepted jobs.
MATCH_COLUMNS = """
    match_score INTEGER,
    match_level TEXT,
    match_strengths TEXT,
    match_gaps TEXT,
    match_reason TEXT,
    match_status TEXT DEFAULT 'PENDING',
    matched_at TEXT
"""

# Open a database with consistent timeout and row access.
def connect_database(path):
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection

# Create both databases and their indexes.
def initialise_databases():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with connect_database(ALL_JOBS_DB) as connection:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, {JOB_COLUMNS})"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_all_status ON jobs(processing_status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_all_seen ON jobs(last_seen)")
    with connect_database(JOBS_DB) as connection:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, {JOB_COLUMNS}, {MATCH_COLUMNS})"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_shortlist_score ON jobs(match_score)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_shortlist_status ON jobs(match_status)")

# Return a dictionary containing a database row.
def row_dict(row):
    return dict(row) if row is not None else None

# Copy a screened job into the accepted shortlist.
def upsert_accepted_job(linkedin_id):
    with connect_database(ALL_JOBS_DB) as source:
        job = source.execute(
            "SELECT * FROM jobs WHERE linkedin_id = ?", (linkedin_id,)
        ).fetchone()
    if job is None:
        raise ValueError(f"Job not found in master database: {linkedin_id}")
    data = dict(job)
    columns = [name for name in data if name != "id"]
    placeholders = ", ".join("?" for _ in columns)
    assignments = ", ".join(
        f"{name}=excluded.{name}" for name in columns if name != "linkedin_id"
    )
    with connect_database(JOBS_DB) as target:
        target.execute(
            f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(linkedin_id) DO UPDATE SET {assignments}",
            [data[name] for name in columns],
        )

# Remove a job from the shortlist after a changed description fails screening.
def remove_accepted_job(linkedin_id):
    with connect_database(JOBS_DB) as connection:
        connection.execute("DELETE FROM jobs WHERE linkedin_id = ?", (linkedin_id,))


# Refresh discovery metadata for a job already in the shortlist.
def update_accepted_job_seen(linkedin_id, last_seen, search_url=None):
    with connect_database(JOBS_DB) as connection:
        connection.execute(
            """UPDATE jobs SET last_seen = ?, search_url = COALESCE(?, search_url)
               WHERE linkedin_id = ?""",
            (last_seen, search_url, linkedin_id),
        )
