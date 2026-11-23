"""Create local configuration from safe examples without overwriting files."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"

def copy_if_missing(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
        print(f"Created: {destination.relative_to(ROOT)}")

def main():
    # Create local folders for personal settings and generated files.
    for folder in [
        "searches", "filters", "prompts", "application_materials",
        "Applications", "Output", "Debugging", "linkedin_profile",
    ]:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    # Copy local search and filter settings only once.
    copy_if_missing(EXAMPLES / "searches/Search_list.py", ROOT / "searches/Search_list.py")
    copy_if_missing(EXAMPLES / "filters/Basic_filters.py", ROOT / "filters/Basic_filters.py")
    # Copy prompt templates and personal preference templates.
    for name in [
        "01_Filter_prompt.txt", "02_Matching_prompt.txt",
        "03_Master_CV_prompt.txt", "04_Tailor_CV_prompt.txt",
        "05_Cover_Letter_prompt.txt", "Candidate_Profile.txt",
        "Search_Preferences.txt",
    ]:
        copy_if_missing(EXAMPLES / "prompts" / name, ROOT / "prompts" / name)
    # Copy application resources without overwriting personal files.
    for source, target in [
        ("Master_CV.tex", "Master_CV.tex"),
        ("Cover_Letter_Template.tex", "Cover_Letter_Template.tex"),
        ("Cover_Letter_Examples.txt", "Cover_Letter_Examples.txt"),
    ]:
        copy_if_missing(EXAMPLES / "application_materials" / source, ROOT / "application_materials" / target)
    # Create a root environment template without real credentials.
    env = ROOT / ".env"
    if not env.exists():
        env.write_text(
            "OPENAI_API_KEY=replace_with_your_api_key\nAPPLICANT_SURNAME=Example\n",
            encoding="utf-8",
",
        )
        print(f"Created: {env.relative_to(ROOT)}")
    print("Local setup complete. Edit the root-level folders before running.")

if __name__ == "__main__":
    main()
