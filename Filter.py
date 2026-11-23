"""Apply basic and AI filtering to jobs in all_jobs.db."""
import json
import sqlite3
import time
from datetime import datetime
from openai import OpenAI
from config import (ALL_JOBS_DB, FILTER_MODEL, FILTER_PROMPT, LOG_FILE, FILTERS_MODULE,
    SEARCH_PREFERENCES_FILE, EXAMPLE_SEARCH_PREFERENCES_FILE)
from database import connect_database, initialise_databases, upsert_accepted_job, remove_accepted_job
from progress_tracker import ProgressTracker

# Load the user's editable basic-filter settings.
TITLE_FILTERS, DESCRIPTION_FILTERS, LOCATION_FILTERS, COMPANY_FILTERS = FILTERS_MODULE.get_filters()

# Create the OpenAI client only when filtering is run.
client = OpenAI()

# Load the external AI screening prompt.
def load_prompt():
    # Load private preferences when available; otherwise use the public example.
    preference_path = (SEARCH_PREFERENCES_FILE if SEARCH_PREFERENCES_FILE.exists()
                      else EXAMPLE_SEARCH_PREFERENCES_FILE)
    preferences = preference_path.read_text(encoding="utf-8").strip()
    # Fill the preference placeholder before analysing jobs.
    return FILTER_PROMPT.read_text(encoding="utf-8").replace(
        "{preferences}", preferences or "No candidate preferences supplied."
    )

def check_basic_filters(job):

    # Get the job title.
    title = (job['title'] or '').strip()

    # Get the job description.
    description = (job['description'] or '').strip()

    # Get the job location.
    location = (job['location'] or '').strip()

    # Get the company name.
    company = (job['company'] or '').strip()

    # Check the title filters.
    for text, reason in TITLE_FILTERS:

        # Check whether the filter string appears in the title.
        if text.lower() in title.lower():

            # Return the rejection reason.
            return reason

    # Check the description filters.
    for text, reason in DESCRIPTION_FILTERS:

        # Check whether the filter string appears in the description.
        if text.lower() in description.lower():

            # Return the rejection reason.
            return reason

    # Check the location filters.
    for text, reason in LOCATION_FILTERS:

        # Check whether the filter string appears in the location.
        if text.lower() in location.lower():

            # Return the rejection reason.
            return reason

    # Check the company filters.
    for text, reason in COMPANY_FILTERS:

        # Check whether the filter string appears in the company.
        if text.lower() in company.lower():

            # Return the rejection reason.
            return reason

    # Return no reason when the job passes.
    return None


# Save a job and its AI analysis to a database.

def analyse_job(job, prompt):

    # Insert the job title into the prompt.
    job_prompt = prompt.replace(
        '{title}',
        job['title'] or ''
    )

    # Insert the job description into the prompt.
    job_prompt = job_prompt.replace(
        '{description}',
        job['description'] or ''
    )

    # Send the job to the OpenAI API.
    response = client.responses.create(
        model=FILTER_MODEL,
        input=job_prompt
    )

    # Extract the model's text response.
    response_text = response.output_text.strip()

    # Parse the response as JSON.
    return json.loads(response_text)


# Update the Prompted status in the source database.

# Update the master record after each filtering outcome.
def update_master(linkedin_id, values):
    assignments = ", ".join(f"{column} = ?" for column in values)
    parameters = list(values.values()) + [linkedin_id]
    with connect_database(ALL_JOBS_DB) as connection:
        connection.execute(
            f"UPDATE jobs SET {assignments} WHERE linkedin_id = ?",
            parameters,
        )

# Process every job that has not completed screening.
def main():
    initialise_databases()
    prompt = load_prompt()
    with connect_database(ALL_JOBS_DB) as connection:
        jobs = connection.execute(
            """SELECT * FROM jobs
               WHERE processing_status IN ('SCRAPED', 'FAILED_BASIC', 'FAILED_AI')
               ORDER BY first_seen"""
        ).fetchall()

    print(f"Jobs awaiting filtering: {len(jobs)}")
    tracker = ProgressTracker("Filtering", len(jobs), "job")
    counts = {"basic_rejected": 0, "ai_kept": 0, "ai_rejected": 0,
              "skipped": 0, "errors": 0}

    for number, job in enumerate(jobs, start=1):
        started = time.perf_counter()
        job_data = dict(job)
        linkedin_id = job_data["linkedin_id"]
        title = (job_data.get("title") or "").strip()
        description = (job_data.get("description") or "").strip()
        tracker.update(number, (title or "Untitled job")[:65])
        print(f"[{number}/{len(jobs)}] {title or 'Untitled job'}")

        if not linkedin_id:
            counts["skipped"] += 1
            print("    SKIPPED: Missing LinkedIn job ID")
            continue
        if not title or not description:
            missing = []
            if not title:
                missing.append("title")
            if not description:
                missing.append("description")
            missing_text = " and ".join(missing)

            # Mark incomplete records until a later scrape supplies the data.
            update_master(linkedin_id, {
                "processing_status": "SKIPPED_MISSING_DATA",
                "processing_error": f"Missing {missing_text}",
            })
            counts["skipped"] += 1
            print(f"    SKIPPED: Missing {missing_text}")
            continue

        # Apply inexpensive user-defined filters first.
        basic_reason = check_basic_filters(job)
        if basic_reason:
            update_master(linkedin_id, {
                "rejected": "Y",
                "rejection_point": "BASIC_FILTER",
                "rejection_reason": basic_reason,
                "filter_reason": basic_reason,
                "processing_status": "REJECTED_BASIC",
                "last_processed": datetime.now().isoformat(timespec="seconds"),
                "processing_error": None,
                "prompted": "Y",
            })
            remove_accepted_job(linkedin_id)
            counts["basic_rejected"] += 1
            print(f"    BASIC REJECT: {basic_reason}")
            continue

        # Record that basic filtering has passed.
        update_master(linkedin_id, {
            "processing_status": "BASIC_FILTERED",
            "rejected": "N",
            "rejection_point": None,
            "rejection_reason": None,
            "filter_reason": None,
        })

        # Request and validate the AI screening result.
        try:
            analysis = analyse_job(job, prompt)
            decision = analysis.get("decision")
            if decision not in ("KEEP", "BIN"):
                raise ValueError(f"Unexpected AI decision: {decision!r}")
        except Exception as error:
            update_master(linkedin_id, {
                "processing_status": "FAILED_AI",
                "processing_error": str(error)[:2000],
                "last_processed": datetime.now().isoformat(timespec="seconds"),
            })
            counts["errors"] += 1
            print(f"    AI ERROR: {error}")
            continue

        # Save AI analysis and the final decision in the master database.
        now = datetime.now().isoformat(timespec="seconds")
        fields = {
            "ai_summary": analysis.get("summary"),
            "ai_job_type": analysis.get("job_type"),
            "ai_phd_requirement": analysis.get("phd_requirement"),
            "ai_subject_area": analysis.get("subject_area"),
            "ai_seniority": analysis.get("seniority"),
            "ai_experience_years": analysis.get("experience_years"),
            "ai_working_language": analysis.get("working_language"),
            "ai_decision": decision,
            "ai_bin_reason": analysis.get("bin_reason"),
            "ai_reason": analysis.get("reason"),
            "prompted": "Y",
            "last_processed": now,
            "processing_error": None,
        }

        if decision == "KEEP":
            fields.update({
                "rejected": "N",
                "rejection_point": None,
                "rejection_reason": None,
                "processing_status": "AI_FILTERED",
            })
            update_master(linkedin_id, fields)
            upsert_accepted_job(linkedin_id)
            counts["ai_kept"] += 1
            print(f"    AI KEEP: {analysis.get('subject_area')}")
        else:
            reason = analysis.get("bin_reason") or analysis.get("reason")
            fields.update({
                "rejected": "Y",
                "rejection_point": "AI_FILTER",
                "rejection_reason": reason,
                "processing_status": "REJECTED_AI",
            })
            update_master(linkedin_id, fields)
            remove_accepted_job(linkedin_id)
            counts["ai_rejected"] += 1
            print(f"    AI REJECT: {reason}")

        print(f"    Time: {time.perf_counter() - started:.2f} s")

    # Print and append a concise processing summary.
    tracker.finish()
    summary = (
        "\nFILTER SUMMARY\n"
        f"Basic rejected: {counts['basic_rejected']}\n"
        f"AI kept: {counts['ai_kept']}\n"
        f"AI rejected: {counts['ai_rejected']}\n"
        f"Skipped: {counts['skipped']}\n"
        f"Errors: {counts['errors']}"
    )
    print(summary)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(summary + "\n")

if __name__ == "__main__":
    main()
