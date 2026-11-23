"""Interactive launcher for the LinkedIn job-search pipeline."""
import subprocess
import sys
from pathlib import Path
from progress_tracker import ProgressTracker, recent_average, format_duration

# Resolve scripts relative to this launcher.
PROJECT_DIR = Path(__file__).resolve().parent

# Define the normal pipeline stages.
SCRIPTS = {
    "2": ("Scrape jobs", "scraper.py"),
    "3": ("Filter jobs", "Filter.py"),
    "4": ("Match jobs", "matching.py"),
    "6": ("Make CV and cover letter", "Make_application.py"),
}

# Run one script using the active virtual environment.
def run_script(script_name):
    script_path = PROJECT_DIR / script_name
    if not script_path.exists():
        print(f"Script not found: {script_path}")
        return False
    print(f"\n{'=' * 40}\nRUNNING: {script_name}\n{'=' * 40}\n")
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(PROJECT_DIR),
    )
    if result.returncode:
        print(f"\nERROR: {script_name} exited with {result.returncode}.")
        return False
    print(f"\n{script_name} completed successfully.")
    return True

# Run scraping, filtering, and matching in sequence.
def run_all():
    # Define the three stages in their execution order.
    stages = ("2", "3", "4")
    # Start a tracker for the complete pipeline.
    tracker = ProgressTracker("Full pipeline", len(stages), "stage")
    # Run each stage and stop if one fails.
    for number, key in enumerate(stages, start=1):
        # Show the current stage and its recent runtime estimate.
        name, script = SCRIPTS[key]
        # Estimate remaining stages from recent script runtimes.
        history_keys = {"2": "Scraping", "3": "Filtering", "4": "Matching"}
        remaining_times = [
            recent_average("runs", history_keys[stage])
            for stage in stages[number - 1:]
        ]
        estimate_seconds = sum(value for value in remaining_times if value is not None)
        estimate = (
            f" | Estimated remaining ~{format_duration(estimate_seconds)}"
            if any(value is not None for value in remaining_times) else ""
        )
        print(f"\nPIPELINE {number}/{len(stages)}: {name}{estimate}")
        # Update the overall pipeline progress.
        tracker.update(number, name)
        # Run the selected script.
        if not run_script(script):
            print("Pipeline stopped; completed stages remain saved.")
            tracker.finish()
            return False
    # Record the complete pipeline runtime.
    tracker.finish()
    print("\nComplete pipeline finished.")
    return True

# Display database maintenance tools.
def debug_menu():
    print("\nDEBUGGING")
    print("1 - Refresh / back up databases")
    print("0 - Return")
    choice = input("\nSelect an option: ").strip()
    if choice == "1":
        run_script(str(Path("maintenance") / "refresh_databases.py"))

# Display the main menu.
def main():
    print(f"Python: {sys.executable}")
    while True:
        print("\n" + "=" * 40)
        print("JOB SEARCH PIPELINE")
        print("=" * 40)
        print("1 - Run all")
        print("2 - Scrape jobs")
        print("3 - Filter jobs")
        print("4 - Match jobs")
        print("5 - Debug / database maintenance")
        print("6 - Make CV / cover letter")
        print("0 - Exit")
        choice = input("\nSelect an option: ").strip()

        if choice == "0":
            print("Goodbye.")
            break
        if choice == "1":
            run_all()
        elif choice in SCRIPTS:
            run_script(SCRIPTS[choice][1])
        elif choice == "5":
            debug_menu()
        else:
            print("Invalid selection.")

if __name__ == "__main__":
    main()
