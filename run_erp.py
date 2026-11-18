
import subprocess
import sys
from pathlib import Path

# Locate the root of the repository
repo_root = Path(__file__).resolve().parent

# Search all subfolders for the analysis script
matches = list(repo_root.rglob("feedback_gain_loss_erp.py"))

if not matches:
    print("ERROR: Could not find feedback_gain_loss_erp.py")
    sys.exit(1)

if len(matches) > 1:
    print("ERROR: Multiple copies of feedback_gain_loss_erp.py found:")
    for match in matches:
        print(match)
    sys.exit(1)

# Get the full path to the analysis script
script_path = matches[0]

print(f"Launching: {script_path}")

# Pass all command-line arguments to the analysis script
subprocess.run(
    [sys.executable, str(script_path), *sys.argv[1:]],
    cwd=str(script_path.parent)
)
