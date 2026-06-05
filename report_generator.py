
from datetime import datetime


CRITICAL = "CRITICAL"
WARNING  = "WARNING"
INFO     = "INFO"
PASS     = "PASS"

SEVERITY_ICON = {
    "CRITICAL": "DANGER",
    "WARNING":  "WARNING",
    "INFO":     "NEED ATTENTION",
    "PASS":     "PASSED",
}

GRADE_BAR = {
    "A": "████████████████████ 100%",
    "B": "████████████████░░░░  80%",
    "C": "████████████░░░░░░░░  60%",
    "D": "████████░░░░░░░░░░░░  40%",
    "F": "████░░░░░░░░░░░░░░░░  20%",
}


def _section_divider(title: str, char: str = "═") -> str:
    line = char * 60
    return f"\n{line}\n  {title}\n{line}\n"


def _findings_block(findings: list, show_pass: bool = False) -> str:
    lines = []
    for f in findings:
        sev  = f.get("severity", "INFO")
        icon = SEVERITY_ICON.get(sev, "")
        if sev == "PASS" and not show_pass:
            continue
        loc = f"  {f['location']}" if f.get("location") else ""
        det = f"  {f['detail']}"   if f.get("detail")   else ""
        lines.append(f"{icon} [{f.get('check_id','?')}] {f.get('message','')}")
        if loc:
            lines.append(loc)
        if det:
            lines.append(det)
        lines.append("")  
    return "\n".join(lines) if lines else "  (none)\n"


def generate_report(audit_result: dict) -> str:
   
    meta     = audit_result.get("audit_metadata", {})
    score    = audit_result.get("score", {})
    findings = audit_result.get("findings", [])
    summary  = audit_result.get("summary", {})

    lines = []

    lines.append("# 📋 LAYER 3 — AUDIT & VALIDATION REPORT")
    lines.append("")
    lines.append(f"**Source File:**       `{meta.get('source_file', 'unknown')}`")
    lines.append(f"**Audit Timestamp:**   `{meta.get('audit_timestamp', '')}`")
    lines.append(f"**Auditor Version:**   `{meta.get('auditor_version', '')}`")
    lines.append(f"**Total Checks Run:**  `{meta.get('total_checks_run', 0)}`")
    lines.append("")

    lines.append(_section_divider("📊 QUALITY SCORE CARD"))
    g = score.get("grade", "?")
    lines.append("```")
    lines.append(f"  OVERALL SCORE : {score.get('score', 0):.1f} / 100")
    lines.append(f"  GRADE         : {g}")
    lines.append(f"  STATUS        : {score.get('status', '')}")
    lines.append(f"  PROGRESS      : {GRADE_BAR.get(g, '')}")
    lines.append("```")
    lines.append("")

    counts = score.get("counts", {})
    lines.append("| Severity    | Count |")
    lines.append("|-------------|-------|")
    lines.append(f"|  CRITICAL | {counts.get('CRITICAL', 0):5} |")
    lines.append(f"|  WARNING  | {counts.get('WARNING',  0):5} |")
    lines.append(f"|  INFO     | {counts.get('INFO',     0):5} |")
    lines.append(f"|  PASS     | {counts.get('PASS',     0):5} |")
    lines.append("")

    criticals = summary.get("critical_issues", [])
    lines.append(_section_divider("CRITICAL ISSUES — Must Fix Before Proceeding"))
    if criticals:
        lines.append(_findings_block(criticals, show_pass=True))
    else:
        lines.append("No critical issues found!\n")

    warnings = summary.get("warnings", [])
    lines.append(_section_divider(" WARNINGS — Review Recommended"))
    if warnings:
        lines.append(_findings_block(warnings, show_pass=True))
    else:
        lines.append("No warnings found!\n")

    info_notes = summary.get("info_notes", [])
    lines.append(_section_divider(" INFO NOTES — Informational"))
    if info_notes:
        lines.append(_findings_block(info_notes, show_pass=True))
    else:
        lines.append(" No informational notes.\n")

    lines.append(_section_divider(" PASSED CHECKS"))
    pass_findings = [f for f in findings if f.get("severity") == "PASS"]
    if pass_findings:
        lines.append(_findings_block(pass_findings, show_pass=True))
    else:
        lines.append("  (no checks passed)\n")

    lines.append(_section_divider(" CHECK GROUP BREAKDOWN"))
    groups = {
        "A": "Structural Completeness",
        "B": "Section Integrity",
        "C": "Number Consistency",
        "D": "Cross-Reference Integrity",
        "E": "Table Integrity",
        "F": "Figure Integrity",
    }
    for gid, gname in groups.items():
        group_findings = [f for f in findings
                          if str(f.get("check_id", "")).startswith(gid)]
        crits   = sum(1 for f in group_findings if f["severity"] == CRITICAL)
        warns   = sum(1 for f in group_findings if f["severity"] == WARNING)
        infos   = sum(1 for f in group_findings if f["severity"] == INFO)
        passes  = sum(1 for f in group_findings if f["severity"] == PASS)

        if crits > 0:
            status_icon = "DANGER"
        elif warns > 0:
            status_icon = "WARNING"
        elif infos > 0:
            status_icon = "NEED ATTENTION"
        else:
            status_icon = "PASSED"

        lines.append(f"{status_icon} **Group {gid} — {gname}**")
        lines.append(f"   Checks: {len(group_findings)} total | "
                     f" {crits} |  {warns} |  {infos} |  {passes}")
        lines.append("")

    lines.append(f"*Report generated by Layer 3 Audit Engine v{meta.get('auditor_version','')} "
                 f"at {meta.get('audit_timestamp','')}*")

    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import argparse

    parser = argparse.ArgumentParser(
        description="Layer 3 Report Generator — convert audit JSON to Markdown report"
    )
    parser.add_argument("input_json", help="Path to audit result JSON (from audit_engine.py)")
    parser.add_argument("--output", "-o", default=None,
                        help="Optional path to save report .md (default: auto-named next to input)")
    args = parser.parse_args()

    with open(args.input_json) as fh:
        audit_result = json.load(fh)

    report = generate_report(audit_result)
    print(report)

    out_path = args.output or args.input_json.replace(".json", "_report.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(f"\n Report saved to: {out_path}")