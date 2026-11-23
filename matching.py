"""Match AI-approved jobs against the user's CV prompt."""
import time
import json
from datetime import datetime
from openai import OpenAI
from config import (ALL_JOBS_DB, JOBS_DB, MATCHING_MODEL, MATCHING_PROMPT, LOG_FILE, INPUT_DIR,
    CANDIDATE_PROFILE_FILE, EXAMPLE_CANDIDATE_PROFILE_FILE)
from database import connect_database, initialise_databases
from progress_tracker import ProgressTracker

# Create the API client when matching is requested.
client = OpenAI()

# Load the external CV-matching prompt.
def load_prompt():
    # Load private candidate evidence or the public template.
    profile_path = (CANDIDATE_PROFILE_FILE if CANDIDATE_PROFILE_FILE.exists()
                    else EXAMPLE_CANDIDATE_PROFILE_FILE)
    candidate_profile = profile_path.read_text(encoding="utf-8").strip()
    # Fill the profile placeholder before matching jobs.
    return MATCHING_PROMPT.read_text(encoding="utf-8").replace(
        "{candidate_profile}", candidate_profile or "No candidate profile supplied."
    )

def analyse_job(job, prompt):

    job_prompt = prompt

    # Insert the job title into the prompt.
    job_prompt = job_prompt.replace(
        '{title}',
        job['title'] or ''
    )

    # Insert the job description into the prompt.
    job_prompt = job_prompt.replace(
        '{description}',
        job['description'] or ''
    )

    # Load optional applicant context when supplied.
    comments_file = INPUT_DIR / 'Applicant_comments.txt'
    comments = comments_file.read_text(encoding='utf-8').strip() if comments_file.exists() else ''

    # Fill the optional applicant-context placeholder.
    job_prompt = job_prompt.replace('{comments}', comments or 'No additional applicant context supplied.')

    # Send the job and CV to the OpenAI API.
    response = client.responses.create(
        model=MATCHING_MODEL,
        input=job_prompt
    )

    # Extract the model's text response.
    response_text = response.output_text.strip()

    # Parse the response as JSON.
    return json.loads(response_text)


# Save a matched job to the output database.

# Store matching results in the accepted-jobs database.
def save_match(job, analysis):
    now = datetime.now().isoformat(timespec="seconds")
    with connect_database(JOBS_DB) as connection:
        connection.execute(
            """UPDATE jobs SET
               match_score = ?, match_level = ?, match_strengths = ?,
               match_gaps = ?, match_reason = ?, match_status = 'COMPLETED',
               processing_status = 'MATCHED', last_processed = ?, matched_at = ?
               WHERE linkedin_id = ?""",
            (
                analysis["match_score"],
                analysis["match_level"],
                str(analysis.get("strengths", "")),
                str(analysis.get("skill_gaps", "")),
                analysis.get("match_reason"),
                now,
                now,
                job["linkedin_id"],
            ),
        )
    with connect_database(ALL_JOBS_DB) as connection:
        connection.execute(
            """UPDATE jobs SET processing_status = 'MATCHED',
               last_processed = ?, processing_error = NULL
               WHERE linkedin_id = ?""",
            (now, job["linkedin_id"]),
        )

# Match every accepted job that has not yet been assessed.
def main():
    initialise_databases()
    prompt = load_prompt()
    with connect_database(JOBS_DB) as connection:
        jobs = connection.execute(
            """SELECT * FROM jobs
               WHERE COALESCE(match_status, 'PENDING') != 'COMPLETED'
               ORDER BY first_seen"""
        ).fetchall()

    print(f"Jobs awaiting CV matching: {len(jobs)}")
    tracker = ProgressTracker("Matching", len(jobs), "job")
    processed = 0
    errors = 0
    for number, job in enumerate(jobs, start=1):
        started = time.perf_counter()
        title = (job["title"] or "").strip()
        description = (job["description"] or "").strip()
        tracker.update(number, title[:65])
        print(f"[{number}/{len(jobs)}] Matching: {title}")
        if not title or not description:
            errors += 1
            print("    SKIPPED: Missing title or description")
            continue

        try:
            analysis = analyse_job(job, prompt)
            score = analysis.get("match_score")
            level = analysis.get("match_level")
            valid_levels = ("Excellent", "Strong", "Good", "Moderate", "Weak", "Very weak")
            if not isinstance(score, int) or not 0 <= score <= 100:
                raise ValueError(f"Invalid match score: {score!r}")
            if level not in valid_levels:
                raise ValueError(f"Invalid match level: {level!r}")
            save_match(job, analysis)
            processed += 1
            print(f"    {score}% - {level}")
        except Exception as error:
            errors += 1
            now = datetime.now().isoformat(timespec="seconds")
            with connect_database(JOBS_DB) as connection:
                connection.execute(
                    """UPDATE jobs SET match_status = 'FAILED'
                       WHERE linkedin_id = ?""",
                    (job["linkedin_id"],),
                )
            with connect_database(ALL_JOBS_DB) as connection:
                connection.execute(
                    """UPDATE jobs SET processing_status = 'FAILED_MATCHING',
                       processing_error = ?, last_processed = ?
                       WHERE linkedin_id = ?""",
                    (str(error)[:2000], now, job["linkedin_id"]),
                )
            print(f"    ERROR: {error}")
        print(f"    Time: {time.perf_counter() - started:.2f} s")

    tracker.finish()
    summary = f"\nMATCHING SUMMARY\nMatched: {processed}\nErrors: {errors}"
    print(summary)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(summary + "\n")

if __name__ == "__main__":
    main()
