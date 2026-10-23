import argparse
import json
from pathlib import Path
from .pipeline import run


def main():
    parser = argparse.ArgumentParser(description="Read-only TACS-3 impedance diagnostics")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--configuration-log", type=Path, help="private file/hash-bound operator setup log")
    parser.add_argument("--aliases", type=Path, help="existing documented legacy identity aliases; never strips G/R")
    parser.add_argument("--threshold", type=float, default=20000, help="descriptive raw-value threshold; not a deployment rule")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.root, args.output or args.root / "impedance_analysis/outputs/latest",
                         args.configuration_log, args.aliases, args.threshold, not args.no_plots), indent=2))


if __name__ == "__main__":
    main()
