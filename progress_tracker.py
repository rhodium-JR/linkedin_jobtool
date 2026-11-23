"""Small terminal progress tracker with recent-run timing estimates."""
import json
import time
from pathlib import Path

# Store recent timing history beside the project databases.
HISTORY_FILE = Path(__file__).resolve().parent / "Output" / "progress_history.json"


# Format seconds as a compact duration.
def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


# Read the saved timing history safely.
def read_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": {}, "runs": {}}


# Save only the ten most recent samples.
def save_sample(section, key, duration):
    history = read_history()
    samples = history.setdefault(section, {}).setdefault(key, [])
    samples.append(round(max(0, duration), 2))
    history[section][key] = samples[-10:]
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")


# Calculate the mean of the ten most recent samples.
def recent_average(section, key):
    samples = read_history().get(section, {}).get(key, [])
    return sum(samples) / len(samples) if samples else None


# Track progress and estimate remaining time.
class ProgressTracker:
    def __init__(self, stage, total, unit="job"):
        self.stage = stage
        self.total = max(0, total)
        self.unit = unit
        self.started = time.perf_counter()
        self.last_update = self.started
        self.last_number = 0

    # Print one readable progress line and update timing history.
    def update(self, current, label=""):
        now = time.perf_counter()
        if current > self.last_number:
            save_sample("items", self.stage, now - self.last_update)
        self.last_update = now
        self.last_number = current
        elapsed = now - self.started
        remaining = max(0, self.total - current)
        average = recent_average("items", self.stage)
        if average is None and current:
            average = elapsed / current
        eta = average * remaining if average is not None else 0
        detail = f" | {label}" if label else ""
        print(
            f"⏳ {self.stage} | {self.unit.title()} {current}/{self.total}"
            f" | Elapsed {format_duration(elapsed)}"
            f" | ETA ~{format_duration(eta)}{detail}",
            flush=True,
        )

    # Store the complete script runtime.
    def finish(self):
        duration = time.perf_counter() - self.started
        save_sample("runs", self.stage, duration)
        print(
            f"✓ {self.stage} finished in {format_duration(duration)}"
            f" | Recent average {format_duration(recent_average('runs', self.stage) or duration)}",
            flush=True,
        )
        return duration
