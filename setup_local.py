"""Create root-level local folders and migrate old private files safely."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
LEGACY_PRIVATE = ROOT / "private"

def copy_if_missing(source, destination):
    # Preserve existing personal files.
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.exists() and not destination.exists():
        shutil.copy2(source, destination)
        print(f"Created: {destination.relative_to(ROOT)}")

def copy_tree_missing(source, destination):
    # Copy only files absent from the destination.
    if not source.exists():
        return
    for item in source.rglob("*"):
        # Keep the original folder structure.
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            print(f"Migrated: {target.relative_to(ROOT)}")

def main():
    # Create root-level folders for local data.
    folders = [
        "searches", "filters", "prompts", "application_materials",
        "Applications", "Output", "Debugging", "linkedin_profile",
    ]
    for folder in folders:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)

    # Migrate old private folders without overwriting files.
    migrations = [
        ("searches", "searches"),
        ("filters", "filters"),
        ("prompts", "prompts"),
        ("application_materials", "application_materials"),
        ("applications", "Applications"),
        ("data/output", "Output"),
        ("data/debugging", "Debugging"),
        ("linkedin_profile", "linkedin_profile"),
    ]
    for old, new in migrations:
        copy_tree_missing(LEGACY_PRIVATE / old, ROOT / new)
    # Preserve an existing private environment file.
    copy_if_missing(LEGACY_PRIVATE / ".env", ROOT / ".env")

    # Copy example search and filter settings when absent.
    copy_if_missing(EXAMPLES / "searches/Search_list.py", ROOT / "searches/Search_list.py")
    copy_if_missing(EXAMPLES / "filters/Basic_filters.py", ROOT / "filters/Basic_filters.py")

    # Copy prompt templates and personal profile templates.
    prompt_names = [
        "01_Filter_prompt.txt", "02_Matching_prompt.txt",
        "03_Master_CV_prompt.txt", "04_Tailor_CV_prompt.txt",
        "05_Cover_Letter_prompt.txt", "Candidate_Profile.txt",
        "Search_Preferences.txt",
    ]
    for name in prompt_names:
        copy_if_missing(EXAMPLES / "prompts" / name, ROOT / "prompts" / name)

    # Copy application resources without replacing personal files.
    materials = [
        ("Master_CV.tex", "Master_CV.tex"),
        ("Cover_Letter_Template.tex", "Cover_Letter_Template.tex"),
        ("Cover_Letter_Examples.txt", "Cover_Letter_Examples.txt"),
    ]
    for source, target in materials:
        copy_if_missing(
            EXAMPLES / "application_materials" / source,
            ROOT / "application_materials" / target,
        )

    # Create a local API-key template if none exists.
    env = ROOT / ".env"
    if not env.exists():
        env.write_text(
            "OPENAI_API_KEY=replace_with_your_api_key\n"
            "APPLICANT_SURNAME=Example\n",
            encoding="utf-8",
        )
        print(f"Created: {env.relative_to(ROOT)}")
    print("Local setup complete. Edit root-level folders before running.")

if __name__ == "__main__":
    main()
