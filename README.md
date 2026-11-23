# LinkedIn Job Scraping and Filtering

A local Python workflow for collecting job listings, filtering them, assessing suitability with an AI model, and preparing application documents.

## Structure

- `Find_jobs.py`, `scraper.py`, `Filter.py`, `matching.py`, `Make_application.py`: pipeline stages
- `config.py`: local paths and safe example fallbacks
- `examples/`: public dummy searches, filters, prompts and application documents
- `searches/`, `filters/`, `prompts/`, `application_materials/`: personal configuration and resources, ignored by Git
- `Output/`, `Debugging/`, `Applications/`, `linkedin_profile/`: local databases, logs, generated documents and browser session, ignored by Git

## Setup

1. Install Python 3.10+, Chrome and dependencies: `pip install -r requirements.txt`.
2. Run `python setup_local.py` to create the root-level local folders and copy safe examples. If an older `private/` folder exists, this script safely copies its files into the new locations without overwriting anything.
3. Edit your personal searches, filters, prompts, candidate profile, search preferences and application materials in the root-level folders.
4. Add your API key to the root `.env` file.
5. Run `python Find_jobs.py`.

The repository includes a dummy LinkedIn search for `Bauer`/farmer jobs and synthetic application-document examples. These examples are fictional and not based on any real person.

## Privacy

Personal files and local data are protected by `.gitignore`. This includes the API key, personal search settings, prompts, CV and cover-letter resources, job records, generated applications, logs and browser session.

Review GitHub Desktop's Changes list before every commit. If a secret was ever committed, deleting it from a file is insufficient; rotate it and remove it from Git history.

Respect LinkedIn's terms, rate limits, and applicable laws. This project is not affiliated with LinkedIn.
