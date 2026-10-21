import argparse
import json
from pathlib import Path

from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Offline TACS-3 behavioral QC and descriptive analysis")
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, help="default: ROOT/behavioral_analysis/outputs/latest")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--condition-key", type=Path, help="optional private documented assignment/delivery CSV")
    parser.add_argument("--roster", type=Path, help="optional private participant/cohort/evidence CSV")
    parser.add_argument("--adjudications", type=Path, help="optional private source_file/sha256/decision/reason CSV")
    parser.add_argument("--no-plots", action="store_true", help="for headless smoke testing only")
    args = parser.parse_args()
    result = run(args.root, args.output or args.root / "behavioral_analysis/outputs/latest",
                 args.config, args.condition_key, args.roster, not args.no_plots, args.adjudications)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
