

import argparse
import json
import os
import sys
from pathlib import Path

from audit_engine     import run_audit
from report_generator import generate_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Layer 3 — PDF Audit & Validation Layer"
    )
    parser.add_argument(
        "input_json",
        help="Path to Layer 2 output JSON file"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Directory to write output files (default: same as input)"
    )
    parser.add_argument(
        "--show-passes",
        action="store_true",
        help="Include PASS checks in terminal output"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any CRITICAL issues found"
    )
    return parser.parse_args()


SEVERITY_COLOR = {
    "CRITICAL": "\033[91m",  
    "WARNING":  "\033[93m",  
    "INFO":     "\033[94m",  
    "PASS":     "\033[92m",  
}
RESET = "\033[0m"


def print_terminal_summary(audit_result: dict, show_passes: bool = False):
    score   = audit_result["score"]
    meta    = audit_result["audit_metadata"]
    summary = audit_result["summary"]

    print("\n" + "═" * 65)
    print("   LAYER 3 — AUDIT & VALIDATION LAYER")
    print("═" * 65)
    print(f"  Source   : {meta['source_file']}")
    print(f"  Checks   : {meta['total_checks_run']} total")
    print(f"  Score    : {score['score']:.1f}/100  │  Grade: {score['grade']}  │  {score['status']}")
    print("─" * 65)

    counts = score["counts"]
    print(f"   CRITICAL : {counts.get('CRITICAL', 0)}")
    print(f"   WARNING  : {counts.get('WARNING',  0)}")
    print(f"   INFO     : {counts.get('INFO',     0)}")
    print(f"   PASS     : {counts.get('PASS',     0)}")
    print("─" * 65)

    for f in summary.get("critical_issues", []):
        c = SEVERITY_COLOR["CRITICAL"]
        print(f"  {c} [{f['check_id']}] {f['message']}{RESET}")
        if f.get("location"):
            print(f"       {f['location']}")

    for f in summary.get("warnings", []):
        c = SEVERITY_COLOR["WARNING"]
        print(f"  {c} [{f['check_id']}] {f['message']}{RESET}")
        if f.get("location"):
            print(f"       {f['location']}")

    if show_passes:
        for f in audit_result.get("findings", []):
            if f["severity"] == "PASS":
                c = SEVERITY_COLOR["PASS"]
                print(f"  {c} [{f['check_id']}] {f['message']}{RESET}")

    print("═" * 65 + "\n")


def main():
    args = parse_args()

    input_path = Path(args.input_json)
    if not input_path.exists():
        print(f" Input file not found: {input_path}")
        sys.exit(1)

    print(f" Loading Layer 2 output: {input_path}")
    with open(input_path,'r',encoding='utf-8') as f:
        doc = json.load(f)

    print(" Running audit checks...")
    audit_result = run_audit(doc)

    print_terminal_summary(audit_result, show_passes=args.show_passes)

    out_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = input_path.stem  

    audit_json_path = out_dir / f"{stem}_audit.json"
    with open(audit_json_path, "w") as f:
        json.dump(audit_result, f, indent=2)
    print(f"Successfully Audit JSON saved  : {audit_json_path}")

    report_md = generate_report(audit_result)
    report_path = out_dir / f"{stem}_audit_report.md"
    with open(report_path, 'w',encoding='utf-8') as f:
        f.write(report_md)
    print(f"Successfully Audit Report saved: {report_path}")

    if args.strict and audit_result["score"]["counts"].get("CRITICAL", 0) > 0:
        print("!!! Attention STRICT MODE: Critical issues found — exiting with code 1")
        sys.exit(1)

    print(f"\n Layer 3 complete. Proceed to Layer 4 when score ≥ 75.\n")


if __name__ == "__main__":
    main()