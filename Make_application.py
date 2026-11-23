"""Generate a master CV, tailored CV, and cover letter in separate stages."""
import argparse
import re
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from openai import OpenAI
from progress_tracker import save_sample, recent_average, format_duration
from config import (
    APPLICATION_MODEL,
    APPLICANT_SURNAME,
    MASTER_CV_PROMPT,
    TAILOR_CV_PROMPT,
    COVER_LETTER_PROMPT,
    APPLICATIONS_DIR,
    APPLICATION_MATERIALS_DIR,
    EXAMPLES_DIR,
)

# Store reusable CV and letter resources in this fixed folder.

EXAMPLE_MATERIALS_DIR = EXAMPLES_DIR / "application_materials"
MASTER_CV_FILE = APPLICATION_MATERIALS_DIR / "Master_CV.tex"
if not MASTER_CV_FILE.exists():
    MASTER_CV_FILE = EXAMPLE_MATERIALS_DIR / "dummy_cv.tex"
COVER_LETTER_TEMPLATE_FILE = APPLICATION_MATERIALS_DIR / "Cover_Letter_Template.tex"
if not COVER_LETTER_TEMPLATE_FILE.exists():
    COVER_LETTER_TEMPLATE_FILE = EXAMPLE_MATERIALS_DIR / "dummy_cover_letter.tex"
COVER_LETTER_EXAMPLES_FILE = APPLICATION_MATERIALS_DIR / "Cover_Letter_Examples.txt"
if not COVER_LETTER_EXAMPLES_FILE.exists():
    COVER_LETTER_EXAMPLES_FILE = EXAMPLE_MATERIALS_DIR / "Cover_Letter_Examples.txt"

# Create one API client for the document-generation session.
MODEL = APPLICATION_MODEL


# Read a UTF-8 text or LaTeX file.
def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


# Save generated text while creating parent folders.
def save_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Saved: {path}", flush=True)
    return path


# Create a Windows-safe filename component.
def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*]', "_", str(value))
    return value.strip(" .")[:90] or "application"


# Build a consistent surname-prefixed application filename.
def applicant_filename(document_type):
    surname = safe_name(APPLICANT_SURNAME)
    return f"{surname}_{document_type}"


# Select one input file through a native dialog.
def choose_file(title, filetypes, required=True):
    root = tk.Tk()
    root.withdraw()
    selected = filedialog.askopenfilename(title=title, filetypes=filetypes)
    root.destroy()
    if not selected and required:
        raise RuntimeError(f"No file selected: {title}")
    return Path(selected) if selected else None


# Select an optional comments file or return blank.
def choose_optional_text(title):
    path = choose_file(
        title,
        [("Text files", "*.txt"), ("All files", "*.*")],
        required=False,
    )
    return read_text(path).strip() if path else ""


# Replace only named placeholders without altering inserted LaTeX.
def fill_prompt(template, values, required):
    missing = [key for key in required if "{" + key + "}" not in template]
    if missing:
        raise ValueError("Prompt is missing placeholders: " + ", ".join(missing))
    pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
    return pattern.sub(
        lambda match: values.get(match.group(1), match.group(0)),
        template,
    )


# Replace a labelled prompt section while preserving its heading and instructions.
def replace_prompt_section(prompt, heading, next_heading, content):
    start = prompt.find(heading)
    if start < 0:
        return prompt, False
    body_start = start + len(heading)
    end = prompt.find(next_heading, body_start)
    if end < 0:
        return prompt, False
    return (
        prompt[:body_start] + "\n" + content.strip() + "\n\n" + prompt[end:],
        True,
    )


# Support both placeholder-based and self-contained cover-letter prompts.
def build_cover_letter_prompt(prompt, values):
    # Use the original six placeholders when the prompt defines them.
    legacy_keys = ("title", "description", "CV", "LATEX_TEMPLATE", "EXAMPLES", "COMMENTS")
    if all("{" + key + "}" in prompt for key in legacy_keys):
        return fill_prompt(prompt, values, required=legacy_keys)

    # Replace the explicit job-description token without touching other braces.
    job_tokens = ("{{JOB_DESCRIPTION}}", "{JOB_DESCRIPTION}")
    token = next((item for item in job_tokens if item in prompt), None)
    if not token:
        raise ValueError(
            "Cover-letter prompt must contain either the six standard placeholders "
            "or {{JOB_DESCRIPTION}}."
        )
    prompt = prompt.replace(token, values["description"])

    # Update embedded source sections using the selected current application files.
    sections = (
        (
            "APPLICANT CV (FACTUAL SOURCE):",
            "COVER LETTER TEMPLATE:",
            values["CV"],
        ),
        (
            "COVER LETTER TEMPLATE:",
            "APPLICANT-WRITTEN EXAMPLES (STYLE REFERENCE ONLY):",
            values["LATEX_TEMPLATE"],
        ),
        (
            "APPLICANT-WRITTEN EXAMPLES (STYLE REFERENCE ONLY):",
            "APPLICANT COMMENTS / ADDITIONAL FACTUAL CONTEXT:",
            values["EXAMPLES"],
        ),
    )
    for heading, next_heading, content in sections:
        prompt, replaced = replace_prompt_section(
            prompt, heading, next_heading, content
        )
        if not replaced:
            raise ValueError(
                f"Self-contained cover-letter prompt is missing section "
                f"'{heading}' or its following heading '{next_heading}'."
            )

    # Replace the final comments section while retaining all preceding instructions.
    comments_heading = "APPLICANT COMMENTS / ADDITIONAL FACTUAL CONTEXT:"
    comments_start = prompt.find(comments_heading)
    if comments_start >= 0:
        prompt = (
            prompt[:comments_start + len(comments_heading)]
            + "\n"
            + values["COMMENTS"].strip()
            + "\n"
        )

    # Add the chosen title as context without changing the prompt file.
    prompt += (
        "\n\nCURRENT APPLICATION TITLE (context only):\n"
        + values["title"].strip()
        + "\n"
    )
    return prompt

# Find section headings written with hyphens or em dashes.
def find_section_heading(response, heading, start_at=0):
    escaped = re.escape(heading)
    pattern = re.compile(
        rf"(?m)^\s*[-—–]{{1,3}}\s*{escaped}\s*[-—–]{{1,3}}\s*$"
    )
    match = pattern.search(response, start_at)
    return match


# Extract a named section from the model's structured response.
def extract_section(response, heading, next_heading=None):
    start_match = find_section_heading(response, heading)
    if not start_match:
        raise ValueError(
            f"AI response is missing section '{heading}'. "
            "Check the response headings in the prompt."
        )
    start = start_match.end()
    end = len(response)
    if next_heading:
        next_match = find_section_heading(response, next_heading, start)
        if next_match:
            end = next_match.start()
    return response[start:end].strip()

# Remove accidental Markdown fences around generated LaTeX.
def clean_latex(content):
    content = content.strip()
    content = re.sub(r"^```(?:latex|tex)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


# Validate that the output resembles a complete LaTeX document.
def validate_latex(content, label):
    content = clean_latex(content)
    if r"\documentclass" not in content or r"\begin{document}" not in content:
        raise ValueError(f"{label} does not contain a complete LaTeX document.")
    if r"\end{document}" not in content:
        raise ValueError(f"{label} is missing \\end{{document}}.")
    return content


# Show a live spinner while the OpenAI request is running.
def spinner(stop_event, label, started):
    symbols = "|/-\\"
    index = 0
    while not stop_event.wait(0.15):
        elapsed = time.perf_counter() - started
        print(
            f"\r{symbols[index % len(symbols)]} Waiting for {label} "
            f"from OpenAI... {elapsed:.0f}s elapsed",
            end="",
            flush=True,
        )
        index += 1
    elapsed = time.perf_counter() - started
    print(
        f"\r[OK] OpenAI finished {label} after {elapsed:.1f}s"
        + " " * 20,
        flush=True,
    )


# Send one prepared prompt to the Responses API.
def ask_openai(client, prompt, label, timing_key=None):
    started = time.perf_counter()
    stop_event = threading.Event()
    print("\n" + "=" * 60, flush=True)
    print(f"STAGE: Sending {label} request", flush=True)
    print(f"Model: {MODEL}", flush=True)
    print(f"Prompt size: {len(prompt):,} characters", flush=True)
    if timing_key:
        average = recent_average("application_generation", timing_key)
        if average is not None:
            print(
                f"Estimated generation time (last {min(10, len(__import__('progress_tracker').read_history().get('application_generation', {}).get(timing_key, [])))}): "
                f"~{format_duration(average)}",
                flush=True,
            )
        else:
            print("Estimated generation time: collecting first timing sample.", flush=True)
    print("Waiting for the API response. This can take a few minutes.", flush=True)

    # Run the spinner separately while the API call blocks.
    spinner_thread = threading.Thread(
        target=spinner,
        args=(stop_event, label, started),
        daemon=True,
    )
    spinner_thread.start()
    try:
        response = client.responses.create(model=MODEL, input=prompt)
    except Exception:
        stop_event.set()
        spinner_thread.join()
        raise
    stop_event.set()
    spinner_thread.join()

    elapsed = time.perf_counter() - started
    if timing_key:
        save_sample("application_generation", timing_key, elapsed)
        average = recent_average("application_generation", timing_key) or elapsed
        print(
            f"Generation time: {format_duration(elapsed)} | "
            f"Recent average: {format_duration(average)}",
            flush=True,
        )
    output = (response.output_text or "").strip()
    print(f"Received {len(output):,} response characters.", flush=True)
    if not output:
        raise RuntimeError("OpenAI returned an empty response.")
    return output

# Create a timestamped output folder for each application.
def application_folder(job_title):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = APPLICATIONS_DIR / f"{safe_name(job_title)}_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# Ask for optional comments without forcing the user to provide them.
def comments_prompt():
    root = tk.Tk()
    root.withdraw()
    answer = simpledialog.askstring(
        "Applicant comments",
        "Optional comments or corrections (leave blank if none):",
        parent=root,
    )
    root.destroy()
    return (answer or "").strip()


# Check permanent application resources before starting a workflow.
def require_application_materials(*paths):
    missing = [path for path in paths if not path.is_file()]
    if missing:
        expected = "\n".join(f"  - {path.name}" for path in missing)
        raise FileNotFoundError(
            "Required application file(s) were not found:\n"
            f"{expected}\n\n"
            "Place these files in this folder:\n"
            f"{APPLICATION_MATERIALS_DIR}\n\n"
            "Use the exact filenames shown above."
        )
    return {path.name: read_text(path) for path in paths}


# Run the master-CV audit and rewrite stage.
def run_master_cv(client):
    cv_path = choose_file(
        "Select your current complete CV in LaTeX",
        [("LaTeX files", "*.tex"), ("Text files", "*.txt"), ("All files", "*.*")],
    )
    cv_source = read_text(cv_path)
    comments = comments_prompt()
    prompt = fill_prompt(
        read_text(MASTER_CV_PROMPT),
        {"CV_LATEX": cv_source, "COMMENTS": comments or "No additional corrections supplied."},
        required=("CV_LATEX", "COMMENTS"),
    )
    response = ask_openai(client, prompt, "master CV review")
    audit = extract_section(response, "AUDIT FINDINGS", "MASTER CV")
    master = extract_section(response, "MASTER CV", "FACTS TO CONFIRM")
    facts = extract_section(response, "FACTS TO CONFIRM")
    master = validate_latex(master, "Master CV")
    folder = application_folder("Master_CV")
    save_text(folder / f"{applicant_filename('CV')}.tex", master)
    save_text(folder / "Audit_Findings.txt", audit)
    save_text(folder / "Facts_To_Confirm.txt", facts)
    print(f"\nMaster CV review saved in: {folder}")


# Ask whether to save the tailored CV beside its job description.
def ask_save_with_job_folder():
    root = tk.Tk()
    root.withdraw()

    # Keep the confirmation window visible above other applications.
    root.attributes("-topmost", True)
    root.update_idletasks()

    # Default to saving beside the job description.
    try:
        answer = messagebox.askyesno(
            "Output location",
            "Save the tailored CV and notes in the same folder as the job description?\n\n"
            "Yes: same folder as the job description\n"
            "No: create a new folder inside Applications",
            default=messagebox.YES,
            parent=root,
        )
    finally:
        root.destroy()

    return answer


# Run the vacancy-specific CV tailoring stage.
def run_tailor_cv(client):
    print("\n[1/6] Checking the permanent master CV.", flush=True)
    materials = require_application_materials(MASTER_CV_FILE)
    master = materials[MASTER_CV_FILE.name]
    print(f"      Loaded: {MASTER_CV_FILE}", flush=True)

    print("\n[2/6] Select the complete job description.", flush=True)
    job_path = choose_file(
        "Select the complete job description",
        [("Text files", "*.txt"), ("All files", "*.*")],
    )
    print(f"      Selected: {job_path}", flush=True)

    print("\n[3/6] Choose the output location.", flush=True)
    save_beside_job = ask_save_with_job_folder()
    if save_beside_job:
        print("      Output: same folder as job description", flush=True)
    else:
        print("      Output: new Applications subfolder", flush=True)

    print("\n[4/6] Enter optional applicant comments.", flush=True)
    comments = comments_prompt()
    print("      Comments received.", flush=True)

    print("\n[5/6] Reading files and preparing the prompt.", flush=True)
    description = read_text(job_path)
    print(f"      Master CV: {len(master):,} characters", flush=True)
    print(f"      Job description: {len(description):,} characters", flush=True)

    print("\n[6/6] Using the job description to identify the role.", flush=True)
    title = (
        "Infer the exact job title from the job description. "
        "Do not ask the applicant separately or guess if it is unclear."
    )
    print("      Job title will be inferred from the job description.", flush=True)

    prompt_template = read_text(TAILOR_CV_PROMPT)
    prompt = fill_prompt(
        prompt_template,
        {
            "MASTER_CV_LATEX": master,
            "title": title,
            "description": description,
            "comments": comments or "No additional applicant comments supplied.",
        },
        required=("MASTER_CV_LATEX", "title", "description", "comments"),
    )
    print(f"      Final prompt: {len(prompt):,} characters", flush=True)

    print("\nSending CV for tailoring. Please wait.", flush=True)
    response = ask_openai(client, prompt, "tailored CV", "tailored_cv")

    print("\nProcessing the response and checking the LaTeX.", flush=True)
    revised = extract_section(response, "REVISED CV", "TAILORING NOTES")
    notes = extract_section(response, "TAILORING NOTES")
    revised = validate_latex(revised, "Tailored CV")

    folder = job_path.parent if save_beside_job else application_folder(title)
    print("\nSaving the tailored CV and notes.", flush=True)
    save_text(folder / f"{applicant_filename('CV')}.tex", revised)
    save_text(folder / "Tailoring_Notes.txt", notes)
    print(f"\n[SUCCESS] Tailored CV saved in: {folder}", flush=True)

# Ask the user to choose an existing cover-letter output folder.
def choose_output_folder(initial_dir=None):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    try:
        selected = filedialog.askdirectory(
            title="Choose where to save the cover letter and notes",
            initialdir=str(initial_dir) if initial_dir else None,
            mustexist=True,
            parent=root,
        )
    finally:
        root.destroy()
    if not selected:
        raise RuntimeError("No output folder selected; cover-letter generation cancelled.")
    return Path(selected)


# Run the vacancy-specific cover-letter stage.
def run_cover_letter(client):
    print("\n[1/6] Checking the permanent cover-letter resources.", flush=True)
    materials = require_application_materials(
        COVER_LETTER_TEMPLATE_FILE, COVER_LETTER_EXAMPLES_FILE
    )
    template = materials[COVER_LETTER_TEMPLATE_FILE.name]
    examples = materials[COVER_LETTER_EXAMPLES_FILE.name]
    print("      Template and examples detected.", flush=True)

    print("\n[2/6] Select the final job-specific CV.", flush=True)
    cv_path = choose_file(
        "Select the final job-specific CV in LaTeX",
        [("LaTeX files", "*.tex"), ("Text files", "*.txt"), ("All files", "*.*")],
    )

    print("\n[3/6] Select the complete job description.", flush=True)
    job_path = choose_file(
        "Select the complete job description",
        [("Text files", "*.txt"), ("All files", "*.*")],
    )

    print("\n[4/6] Choose the output folder.", flush=True)
    folder = choose_output_folder(job_path.parent)
    print(f"      Output: {folder}", flush=True)

    print("\n[5/6] Enter optional applicant comments and job title.", flush=True)
    comments = comments_prompt()
    title = simpledialog.askstring(
        "Job title", "Enter the exact job title:"
    ) or job_path.stem

    print("\n[6/6] Reading files and preparing the prompt.", flush=True)
    cv = read_text(cv_path)
    description = read_text(job_path)
    print(f"      CV: {len(cv):,} characters", flush=True)
    print(f"      Job description: {len(description):,} characters", flush=True)
    prompt = build_cover_letter_prompt(
        read_text(COVER_LETTER_PROMPT),
        {
            "title": title,
            "description": description,
            "CV": cv,
            "LATEX_TEMPLATE": template,
            "EXAMPLES": examples,
            "COMMENTS": comments or "No additional applicant comments supplied.",
        },
    )

    response = ask_openai(client, prompt, "cover letter", "cover_letter")

    # Accept the prompt's requested complete LaTeX output directly.
    if find_section_heading(response, "COVER LETTER"):
        letter = extract_section(response, "COVER LETTER", "APPLICATION NOTES")
        if find_section_heading(response, "APPLICATION NOTES"):
            notes = extract_section(response, "APPLICATION NOTES")
        else:
            notes = "No application notes were requested by the active prompt."
    else:
        # The current prompt requests only a complete LaTeX document.
        letter = response
        notes = (
            "The active cover-letter prompt requests only the complete "
            "LaTeX document, so no separate application notes were returned."
        )

    # Validate and save the generated LaTeX and supporting files.
    letter = validate_latex(letter, "Cover letter")
    save_text(folder / f"{applicant_filename('Cover_Letter')}.tex", letter)
    save_text(folder / "Application_Notes.txt", notes)
    save_text(folder / "Job_Description.txt", description)
    print(f"\n[SUCCESS] Cover letter saved in: {folder}")




# Generate a tailored CV and immediately use it for the cover letter.
def run_complete_application(client):
    print("\nCOMPLETE APPLICATION: TAILORED CV + COVER LETTER", flush=True)

    # Check every permanent resource before starting API work.
    materials = require_application_materials(
        MASTER_CV_FILE, COVER_LETTER_TEMPLATE_FILE, COVER_LETTER_EXAMPLES_FILE
    )
    master = materials[MASTER_CV_FILE.name]
    template = materials[COVER_LETTER_TEMPLATE_FILE.name]
    examples = materials[COVER_LETTER_EXAMPLES_FILE.name]

    # Select the vacancy only once for both documents.
    print("\n[1/7] Select the complete job description.", flush=True)
    job_path = choose_file(
        "Select the complete job description",
        [("Text files", "*.txt"), ("All files", "*.*")],
    )
    description = read_text(job_path)

    # Choose one destination for both generated documents.
    print("\n[2/7] Choose the output folder for both documents.", flush=True)
    folder = choose_output_folder(job_path.parent)
    print(f"      Both documents will be saved in: {folder}", flush=True)

    # Collect optional comments once and reuse them in both prompts.
    print("\n[3/7] Enter optional applicant comments.", flush=True)
    comments = comments_prompt()
    comments_text = comments or "No additional applicant comments supplied."

    # Infer the vacancy title from the job description.
    title = (
        "Infer the exact job title from the job description. "
        "Do not ask the applicant separately or guess if it is unclear."
    )

    # Prepare the tailored CV prompt using the permanent master CV.
    print("\n[4/7] Preparing the tailored CV request.", flush=True)
    tailor_prompt = fill_prompt(
        read_text(TAILOR_CV_PROMPT),
        {
            "MASTER_CV_LATEX": master,
            "title": title,
            "description": description,
            "comments": comments_text,
        },
        required=("MASTER_CV_LATEX", "title", "description", "comments"),
    )
    print(f"      Master CV: {len(master):,} characters", flush=True)
    print(f"      Job description: {len(description):,} characters", flush=True)

    # Generate and validate the vacancy-specific CV.
    print("\n[5/7] Generating the tailored CV.", flush=True)
    tailor_response = ask_openai(client, tailor_prompt, "tailored CV", "tailored_cv")
    revised_cv = extract_section(tailor_response, "REVISED CV", "TAILORING NOTES")
    tailoring_notes = extract_section(tailor_response, "TAILORING NOTES")
    revised_cv = validate_latex(revised_cv, "Tailored CV")

    # Save the CV before starting the cover-letter request.
    cv_output = save_text(folder / f"{applicant_filename('CV')}.tex", revised_cv)
    save_text(folder / "Tailoring_Notes.txt", tailoring_notes)
    print(f"[SUCCESS] Tailored CV saved: {cv_output}", flush=True)

    # Build the cover-letter prompt using the newly tailored CV.
    print("\n[6/7] Preparing the cover letter from the tailored CV.", flush=True)
    cover_prompt = build_cover_letter_prompt(
        read_text(COVER_LETTER_PROMPT),
        {
            "title": title,
            "description": description,
            "CV": revised_cv,
            "LATEX_TEMPLATE": template,
            "EXAMPLES": examples,
            "COMMENTS": comments_text,
        },
    )
    print(f"      Tailored CV supplied: {len(revised_cv):,} characters", flush=True)

    # Generate and validate the cover letter using that exact CV.
    print("\n[7/7] Generating the cover letter.", flush=True)
    letter_response = ask_openai(client, cover_prompt, "cover letter", "cover_letter")

    # Accept either complete LaTeX or the older headed response format.
    if find_section_heading(letter_response, "COVER LETTER"):
        letter = extract_section(letter_response, "COVER LETTER", "APPLICATION NOTES")
        if find_section_heading(letter_response, "APPLICATION NOTES"):
            letter_notes = extract_section(letter_response, "APPLICATION NOTES")
        else:
            letter_notes = "No separate application notes were returned."
    else:
        letter = letter_response
        letter_notes = (
            "The active prompt requests only the complete LaTeX document; "
            "no separate application notes were returned."
        )

    # Save the cover letter and the shared job description.
    letter = validate_latex(letter, "Cover letter")
    save_text(folder / f"{applicant_filename('Cover_Letter')}.tex", letter)
    save_text(folder / "Application_Notes.txt", letter_notes)
    save_text(folder / "Job_Description.txt", description)

    # Confirm both application documents are ready.
    print("\n[COMPLETE] Tailored CV and cover letter generated.", flush=True)
    cv_filename = folder / f"{applicant_filename('CV')}.tex"
    letter_filename = folder / f"{applicant_filename('Cover_Letter')}.tex"
    print(f"      Tailored CV: {cv_filename}", flush=True)
    print(f"      Cover letter: {letter_filename}", flush=True)
    print(f"      Output folder: {folder}", flush=True)



# Display the independent document-generation choices.
def main():
    print("\nAPPLICATION DOCUMENT GENERATOR", flush=True)
    print(f"Using application model: {MODEL}", flush=True)
    print("1 - Review and create master CV")
    print("2 - Tailor master CV to a job")
    print("3 - Generate cover letter")
    print("4 - Generate tailored CV + cover letter")
    print("0 - Return")
    choice = input("\nSelect an option: ").strip()
    if choice == "0":
        return 0
    actions = {"1": run_master_cv, "2": run_tailor_cv, "3": run_cover_letter, "4": run_complete_application}
    if choice not in actions:
        print("Invalid selection.")
        return 1
    client = OpenAI(timeout=600)
    actions[choice](client)
    return 0


# Support direct command-line execution.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate application documents.")
    parser.add_argument("--cli", action="store_true", help="Run without popup completion.")
    args = parser.parse_args()
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
