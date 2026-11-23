# LinkedIn Job Scraping and Filtering

A local Python workflow for collecting job listings, filtering them, assessing suitability with an AI model, and preparing application documents. Personal configuration and data are stored in the ignored `private/` directory.

## Structure

- `scraper.py`, `Filter.py`, `matching.py`, `Make_application.py`: pipeline stages
- `config.py`: private-first paths and safe example fallbacks
- `examples/`: public dummy searches, filters, prompts and application documents
- `private/`: local-only searches, prompts, CV materials, databases, outputs, logs and LinkedIn browser profile (ignored by Git)

## Setup

1. Install Python 3.10+, Chrome and dependencies: `pip install -r requirements.txt`.
2. Run `python setup_private.py` to create the private workspace from examples.
3. Edit your personal searches, filters, prompts and application materials under `private/`; add your API key to `private/.env`.
4. Run `python Find_jobs.py`.

The repository includes a dummy LinkedIn search for `Bauer`/farmer jobs and synthetic application-document examples. These examples are fictional and not based on any real person.

## Privacy

Everything in `private/` is excluded from Git. Keep API keys, personal prompts, CVs, cover letters, search URLs, job records, generated applications, logs and browser sessions there. Review GitHub Desktop's Changes list before every commit. If a secret was ever committed, deleting it from a file is insufficient; rotate it and remove it from Git history.

Respect LinkedIn's terms, rate limits, and applicable laws. This project is not affiliated with LinkedIn.
