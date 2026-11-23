"""Create private configuration from safe examples without overwriting files."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / "private"
EXAMPLES = ROOT / "examples"

def copy_if_missing(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
        print(f"Created: {destination.relative_to(ROOT)}")

def main():
    # Create private directories for personal data.
    for folder in ["searches", "filters", "prompts", "application_materials", "applications", "data/output", "data/debugging", "linkedin_profile"]:
        (PRIVATE / folder).mkdir(parents=True, exist_ok=True)
    # Copy example configuration only when no personal file exists.
    copy_if_missing(EXAMPLES / "searches/Search_list.py", PRIVATE / "searches/Search_list.py")
    copy_if_missing(EXAMPLES / "filters/Basic_filters.py", PRIVATE / "filters/Basic_filters.py")
    for name in ["01_Filter_prompt.txt", "02_Matching_prompt.txt", "03_Master_CV_prompt.txt", "04_Tailor_CV_prompt.txt", "05_Cover_Letter_prompt.txt"]:
        copy_if_missing(EXAMPLES / "prompts" / name, PRIVATE / "prompts" / name)
    for source, target in [("Master_CV.tex", "Master_CV.tex"), ("Cover_Letter_Template.tex", "Cover_Letter_Template.tex"), ("Cover_Letter_Examples.txt", "Cover_Letter_Examples.txt")]:
        copy_if_missing(EXAMPLES / "application_materials" / source, PRIVATE / "application_materials" / target)
    # Create a safe environment template without a real credential.
    env = PRIVATE / ".env"
    if not env.exists():
        env.write_text("OPENAI_API_KEY=replace_with_your_api_key\nAPPLICANT_SURNAME=Example\n", encoding="utf-8")
        print(f"Created: {env.relative_to(ROOT)}")
    print("Private setup complete. Edit files under private/ before running.")

if __name__ == "__main__":
    main()
