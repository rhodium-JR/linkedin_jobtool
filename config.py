"""Central paths and settings with local-first, public-example fallbacks."""
from pathlib import Path
import os

PROJECT_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = PROJECT_DIR / "examples"

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

# Personal configuration stays in root-level, gitignored folders.
INPUT_DIR = PROJECT_DIR / "prompts"
OUTPUT_DIR = PROJECT_DIR / "Output"
DEBUG_DIR = PROJECT_DIR / "Debugging"
HISTORY_DIR = DEBUG_DIR / "history"
APPLICATIONS_DIR = PROJECT_DIR / "Applications"
APPLICATION_MATERIALS_DIR = PROJECT_DIR / "application_materials"
LINKEDIN_PROFILE_DIR = Path(
    os.getenv("LINKEDIN_PROFILE_DIR", str(PROJECT_DIR / "linkedin_profile"))
).expanduser()

# Databases and logs stay local.
ALL_JOBS_DB = OUTPUT_DIR / "all_jobs.db"
JOBS_DB = OUTPUT_DIR / "jobs.db"
LOG_FILE = OUTPUT_DIR / "log.txt"

# Prefer personal prompt files; fall back to safe public examples.
def local_or_example(filename):
    local_path = INPUT_DIR / filename
    example_path = EXAMPLES_DIR / "prompts" / filename
    return local_path if local_path.exists() else example_path

FILTER_PROMPT = local_or_example("01_Filter_prompt.txt")
CANDIDATE_PROFILE_FILE = INPUT_DIR / "Candidate_Profile.txt"
EXAMPLE_CANDIDATE_PROFILE_FILE = EXAMPLES_DIR / "prompts" / "Candidate_Profile.txt"
SEARCH_PREFERENCES_FILE = INPUT_DIR / "Search_Preferences.txt"
EXAMPLE_SEARCH_PREFERENCES_FILE = EXAMPLES_DIR / "prompts" / "Search_Preferences.txt"
MATCHING_PROMPT = local_or_example("02_Matching_prompt.txt")
MASTER_CV_PROMPT = local_or_example("03_Master_CV_prompt.txt")
TAILOR_CV_PROMPT = local_or_example("04_Tailor_CV_prompt.txt")
COVER_LETTER_PROMPT = local_or_example("05_Cover_Letter_prompt.txt")

# Use a personal surname only when set locally.
APPLICANT_SURNAME = os.getenv("APPLICANT_SURNAME", "Example").strip() or "Example"

# Import personal configuration when present, otherwise public examples.
def load_personal_module(local_path, example_path, module_name):
    import importlib.util
    chosen = local_path if local_path.exists() else example_path
    spec = importlib.util.spec_from_file_location(module_name, chosen)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

SEARCH_LIST_MODULE = load_personal_module(
    PROJECT_DIR / "searches" / "Search_list.py",
    EXAMPLES_DIR / "searches" / "Search_list.py",
    "job_search_list_config",
)
FILTERS_MODULE = load_personal_module(
    PROJECT_DIR / "filters" / "Basic_filters.py",
    EXAMPLES_DIR / "filters" / "Basic_filters.py",
    "job_basic_filters_config",
)

FILTER_MODEL = os.getenv("FILTER_MODEL", "gpt-5-mini")
MATCHING_MODEL = os.getenv("MATCHING_MODEL", "gpt-5-mini")
APPLICATION_MODEL = os.getenv("APPLICATION_MODEL", "gpt-5-mini")
