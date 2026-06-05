

import json
import re
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

CRITICAL = "CRITICAL"
WARNING  = "WARNING"
INFO     = "INFO"
PASS     = "PASS"

SEVERITY_ICON = {
    CRITICAL: "DANGER",
    WARNING:  "WARNING",
    INFO:     "NEED ATTENTION",
    PASS:     "PASSED",
}

SEVERITY_WEIGHT = {CRITICAL: 15, WARNING: 5, INFO: 0, PASS: 0}

TRIVIAL_VALUES = set(range(0, 21))
TRIVIAL_VALUES.update({25, 30, 50, 100, 128, 200, 201, 202, 209,
                        256, 258, 299, 300, 301, 384, 512, 1024})


def finding(check_id: str, severity: str, message: str,
            detail: Any = None, location: str = "") -> dict:
    return {
        "check_id":  check_id,
        "severity":  severity,
        "icon":      SEVERITY_ICON[severity],
        "message":   message,
        "detail":    detail,
        "location":  location,
    }


def check_structural_completeness(doc: dict) -> list:
    findings = []

    for key in ["metadata", "sections", "tables", "figures", "numbers"]:
        if key not in doc:
            findings.append(finding("A1", CRITICAL, f"Missing top-level key: '{key}'", location="root"))
        else:
            findings.append(finding("A1", PASS, f"Top-level key present: '{key}'"))

    meta = doc.get("metadata", {})
    for field in ["filename", "total_pages", "extraction_timestamp", "extractor_version"]:
        if field not in meta or meta[field] in [None, "", 0]:
            findings.append(finding("A2", WARNING, f"Metadata field missing or empty: '{field}'", location="metadata"))
        else:
            findings.append(finding("A2", PASS, f"Metadata field OK: '{field}'"))

    sections = doc.get("sections", [])
    if not sections:
        findings.append(finding("A3", CRITICAL, "No sections extracted — document body is empty", location="sections"))
    else:
        findings.append(finding("A3", PASS, f"{len(sections)} section(s) found"))

    total_pages = meta.get("total_pages", 0)
    if isinstance(total_pages, int) and total_pages <= 0:
        findings.append(finding("A4", CRITICAL, f"total_pages is {total_pages} — invalid", location="metadata.total_pages"))
    else:
        findings.append(finding("A4", PASS, f"total_pages = {total_pages}"))

    return findings


def check_section_integrity(doc: dict) -> list:
    findings    = []
    sections    = doc.get("sections", [])
    total_pages = doc.get("metadata", {}).get("total_pages", 9999)

    if not sections:
        findings.append(finding("B0", INFO, "No sections to check"))
        return findings

    for i, sec in enumerate(sections):
        loc = f"sections[{i}] id={sec.get('section_id','?')}"
        for field in ["section_id", "title", "page_start", "page_end", "text"]:
            if field not in sec or sec[field] in [None, ""]:
                findings.append(finding("B1", WARNING, f"Section missing field: '{field}'", location=loc))

        ps, pe = sec.get("page_start"), sec.get("page_end")
        if isinstance(ps, int) and isinstance(pe, int):
            if ps > pe:
                findings.append(finding("B2", CRITICAL, f"page_start ({ps}) > page_end ({pe})", location=loc))
            elif pe > total_pages:
                findings.append(finding("B2", WARNING, f"page_end ({pe}) exceeds total_pages ({total_pages})", location=loc))
            else:
                findings.append(finding("B2", PASS, f"Page range valid: {ps}–{pe}", location=loc))

        text = sec.get("text", "")
        if isinstance(text, str) and len(text.strip()) < 20:
            findings.append(finding("B3", WARNING, f"Section text very short ({len(text.strip())} chars)",
                detail={"text_preview": text.strip()[:80]}, location=loc))

    starts   = [s.get("page_start") for s in sections if isinstance(s.get("page_start"), int)]
    order_ok = True
    for i in range(1, len(starts)):
        if starts[i] < starts[i - 1]:
            findings.append(finding("B4", WARNING, f"Section order mismatch at index {i} (page {starts[i]} after {starts[i-1]})"))
            order_ok = False
    if order_ok:
        findings.append(finding("B4", PASS, "Section page ordering verified"))

    gaps        = []
    sorted_secs = sorted(sections, key=lambda s: s.get("page_start", 0))
    for i in range(1, len(sorted_secs)):
        prev_end   = sorted_secs[i - 1].get("page_end",   0)
        curr_start = sorted_secs[i].get("page_start", 0)
        if curr_start - prev_end > 1:
            gaps.append((prev_end, curr_start))
    if gaps:
        findings.append(finding("B5", INFO, f"Page gaps between sections: {gaps}", detail={"gaps": gaps}))
    else:
        findings.append(finding("B5", PASS, "No page gaps between sections"))

    return findings


def check_number_consistency(doc: dict) -> list:
    findings = []
    numbers  = doc.get("numbers", [])

    if not numbers:
        findings.append(finding("C0", INFO, "No numbers extracted — skipping number checks"))
        return findings

    c1_missing = []
    for i, num in enumerate(numbers):
        for field in ["number_id", "value", "context", "page"]:
            if field not in num or num[field] in [None, ""]:
                c1_missing.append(f"numbers[{i}].{field}")
    if c1_missing:
        findings.append(finding("C1", WARNING,
            f"{len(c1_missing)} missing fields across number entries",
            detail={"examples": c1_missing[:5]}))
    else:
        findings.append(finding("C1", PASS, "All number entries have required fields"))

    unit_val_map = defaultdict(list)
    for num in numbers:
        val  = num.get("value")
        unit = num.get("unit", "")
        if val is not None and float(val) not in TRIVIAL_VALUES:
            unit_val_map[(unit, val)].append(num.get("number_id", "?"))

    suspicious = {k: v for k, v in unit_val_map.items() if len(v) > 5}
    if suspicious:
        top = sorted(suspicious.items(), key=lambda x: -len(x[1]))[:8]
        summary = [f"{val} ({unit or 'no unit'}) × {len(ids)}"
                   for (unit, val), ids in top]
        findings.append(finding(
            "C2", INFO,
            f"{len(suspicious)} non-trivial value(s) repeat suspiciously often — "
            f"likely repeated table/header rows in extraction (does not affect score)",
            detail={"top_repeats": summary}
        ))
    else:
        findings.append(finding("C2", PASS, "No suspicious duplicate number values"))

    values = [n["value"] for n in numbers if isinstance(n.get("value"), (int, float))]
    if len(values) >= 4:
        mean  = statistics.mean(values)
        stdev = statistics.stdev(values)
        if stdev > 0:
            seen_vals = set()
            outliers  = []
            for num in numbers:
                v = num.get("value")
                if isinstance(v, (int, float)) and v not in seen_vals:
                    z = abs(v - mean) / stdev
                    if z > 4:
                        seen_vals.add(v)
                        outliers.append({
                            "value":   v,
                            "unit":    num.get("unit", ""),
                            "z_score": round(z, 1),
                            "context": num.get("context", "")[:100],
                        })
            if outliers:
                findings.append(finding(
                    "C3", WARNING,
                    f"{len(outliers)} unique outlier value(s) detected (z-score > 4) — "
                    f"verify these are real data, not extraction noise",
                    detail={"outliers": outliers}
                ))
            else:
                findings.append(finding("C3", PASS, "No statistical outliers (z-score ≤ 4)"))
        else:
            findings.append(finding("C3", PASS, "All values identical — no outlier analysis needed"))
    else:
        findings.append(finding("C3", INFO, f"Too few numbers ({len(values)}) for outlier analysis"))

    pct_pattern  = re.compile(r'%|percent', re.I)
    pct_nums     = [n for n in numbers if pct_pattern.search(str(n.get("unit","")) + str(n.get("context","")))]
    pct_over_100 = [n for n in pct_nums if isinstance(n.get("value"), (int, float)) and n["value"] > 100]
    if pct_over_100:
        findings.append(finding("C4", WARNING,
            f"{len(pct_over_100)} percentage value(s) > 100 — possible unit error",
            detail={"examples": [{"id": n.get("number_id"), "value": n.get("value"),
                                   "context": n.get("context","")[:80]} for n in pct_over_100[:5]]}))
    else:
        findings.append(finding("C4", PASS, "No percentage values > 100 detected"))

    total  = len(numbers)
    unique = len({n.get("value") for n in numbers if n.get("value") is not None})
    ratio  = unique / total if total > 0 else 1.0
    if ratio < 0.1:
        findings.append(finding("C5", WARNING,
            f"Very low number diversity: {unique} unique / {total} total ({ratio:.0%}) — "
            f"extractor may be capturing repeated page numbers or table headers",
            detail={"unique": unique, "total": total, "ratio": f"{ratio:.0%}"}))
    elif ratio < 0.25:
        findings.append(finding("C5", INFO,
            f"Low number diversity: {unique} unique / {total} total ({ratio:.0%}) — "
            f"review whether page numbers/headers are inflating count"))
    else:
        findings.append(finding("C5", PASS,
            f"Number diversity healthy: {unique} unique / {total} total ({ratio:.0%})"))

    findings.append(finding("C0", PASS, f"{len(numbers)} number(s) audited"))
    return findings


def check_cross_references(doc: dict) -> list:
    findings  = []
    sections  = doc.get("sections", [])
    tables    = doc.get("tables",   [])
    figures   = doc.get("figures",  [])
    full_text = " ".join(s.get("text", "") for s in sections).lower()

    valid_ids = {s.get("section_id") for s in sections}

    d1_bad = [f"Table '{t.get('table_id')}' → '{t.get('section_ref')}'"
              for t in tables if t.get("section_ref") and t.get("section_ref") not in valid_ids]
    if d1_bad:
        findings.append(finding("D1", WARNING, f"{len(d1_bad)} table(s) have invalid section_ref", detail={"bad": d1_bad}))
    elif tables:
        findings.append(finding("D1", PASS, "All table section_refs valid"))

    d2_bad = [f"Figure '{f.get('figure_id')}' → '{f.get('section_ref')}'"
              for f in figures if f.get("section_ref") and f.get("section_ref") not in valid_ids]
    if d2_bad:
        findings.append(finding("D2", WARNING, f"{len(d2_bad)} figure(s) have invalid section_ref", detail={"bad": d2_bad}))
    elif figures:
        findings.append(finding("D2", PASS, "All figure section_refs valid"))

    mentioned_tables     = set(re.findall(r'table\s+(\d+)', full_text, re.I))
    extracted_table_nums = set()
    for tbl in tables:
        m = re.search(r'(\d+)', tbl.get("table_id", ""))
        if m: extracted_table_nums.add(m.group(1))
    missing_t = mentioned_tables - extracted_table_nums
    if missing_t:
        findings.append(finding("D3", WARNING, f"Text references Table(s) {sorted(missing_t)} — not extracted", detail={"missing": sorted(missing_t)}))
    else:
        findings.append(finding("D3", PASS, "All text-referenced tables extracted"))

    mentioned_figs     = set(re.findall(r'fig(?:ure)?\.?\s*(\d+)', full_text, re.I))
    extracted_fig_nums = set()
    for fig in figures:
        m = re.search(r'(\d+)', fig.get("figure_id", ""))
        if m: extracted_fig_nums.add(m.group(1))
    missing_f = mentioned_figs - extracted_fig_nums
    if missing_f:
        findings.append(finding("D4", WARNING, f"Text references Figure(s) {sorted(missing_f)} — not extracted", detail={"missing": sorted(missing_f)}))
    else:
        findings.append(finding("D4", PASS, "All text-referenced figures extracted"))

    findings.append(finding("D5", PASS,
        f"Cross-reference scan complete: {len(mentioned_tables)} table refs, {len(mentioned_figs)} figure refs"))

    return findings


def check_table_integrity(doc: dict) -> list:
    findings = []
    tables   = doc.get("tables", [])

    if not tables:
        findings.append(finding("E0", INFO, "No tables extracted — skipping table checks"))
        return findings

    for tbl in tables:
        loc     = f"tables id={tbl.get('table_id','?')}"
        headers = tbl.get("headers", [])
        rows    = tbl.get("rows",    [])

        if not headers and not rows:
            findings.append(finding("E1", WARNING, "Table has no headers and no rows", location=loc))
            continue
        if not headers:
            findings.append(finding("E2", WARNING, "Table has rows but no headers", location=loc))

        expected_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
        bad_rows      = [{"row_index": r_i, "expected": expected_cols, "got": len(row)}
                         for r_i, row in enumerate(rows) if len(row) != expected_cols]
        if bad_rows:
            findings.append(finding("E3", WARNING, f"{len(bad_rows)} row(s) with inconsistent column count",
                detail={"bad_rows": bad_rows[:5]}, location=loc))
        else:
            findings.append(finding("E3", PASS, f"Table shape OK: {len(rows)}×{expected_cols}", location=loc))

        if not tbl.get("caption", "").strip():
            findings.append(finding("E4", INFO, "Table has no caption", location=loc))
        else:
            findings.append(finding("E4", PASS, "Table has caption", location=loc))

        empty_rows = [i for i, r in enumerate(rows) if all(str(c).strip() == "" for c in r)]
        if empty_rows:
            findings.append(finding("E5", INFO, f"Table has {len(empty_rows)} empty row(s)",
                detail={"indices": empty_rows}, location=loc))

    findings.append(finding("E0", PASS, f"{len(tables)} table(s) audited"))
    return findings


def check_figure_integrity(doc: dict) -> list:
    findings = []
    figures  = doc.get("figures", [])

    if not figures:
        findings.append(finding("F0", INFO, "No figures extracted — skipping figure checks"))
        return findings

    for fig in figures:
        loc   = f"figures id={fig.get('figure_id','?')}"
        total = doc.get("metadata", {}).get("total_pages", 9999)

        if not fig.get("caption", "").strip():
            findings.append(finding("F1", WARNING, "Figure has no caption", location=loc))
        else:
            findings.append(finding("F1", PASS, "Figure has caption", location=loc))

        insight = fig.get("semantic_insight", "")
        if not insight or len(insight.strip()) < 10:
            findings.append(finding("F2", WARNING, "Figure missing semantic insight",
                detail={"insight": insight}, location=loc))
        else:
            findings.append(finding("F2", PASS, f"Semantic insight present ({len(insight)} chars)", location=loc))

        page = fig.get("page")
        if not isinstance(page, int) or page < 1 or page > total:
            findings.append(finding("F3", WARNING, f"Figure has invalid page number: {page}", location=loc))
        else:
            findings.append(finding("F3", PASS, f"Figure page valid: {page}", location=loc))

    findings.append(finding("F0", PASS, f"{len(figures)} figure(s) audited"))
    return findings


def compute_score(all_findings: list) -> dict:
    counts = {CRITICAL: 0, WARNING: 0, INFO: 0, PASS: 0}
    for f in all_findings:
        counts[f.get("severity", INFO)] = counts.get(f.get("severity", INFO), 0) + 1

    penalty = (counts[CRITICAL] * SEVERITY_WEIGHT[CRITICAL] +
               counts[WARNING]  * SEVERITY_WEIGHT[WARNING])
    score   = max(0, 100 - penalty)

    if   score >= 90: grade, status = "A", "EXCELLENT"
    elif score >= 75: grade, status = "B", "GOOD"
    elif score >= 60: grade, status = "C", "FAIR"
    elif score >= 40: grade, status = "D", "POOR"
    else:             grade, status = "F", "CRITICAL — DO NOT PROCEED"

    return {"score": score, "grade": grade, "status": status,
            "counts": counts, "penalty": penalty}


def run_audit(doc: dict) -> dict:
    all_findings  = []
    all_findings += check_structural_completeness(doc)
    all_findings += check_section_integrity(doc)
    all_findings += check_number_consistency(doc)
    all_findings += check_cross_references(doc)
    all_findings += check_table_integrity(doc)
    all_findings += check_figure_integrity(doc)

    score_info = compute_score(all_findings)

    return {
        "audit_metadata": {
            "auditor_version":  "1.1.0",
            "audit_timestamp":  datetime.utcnow().isoformat() + "Z",
            "source_file":      doc.get("metadata", {}).get("filename", "unknown"),
            "total_checks_run": len(all_findings),
        },
        "score":    score_info,
        "findings": all_findings,
        "summary": {
            "critical_issues": [f for f in all_findings if f["severity"] == CRITICAL],
            "warnings":        [f for f in all_findings if f["severity"] == WARNING],
            "info_notes":      [f for f in all_findings if f["severity"] == INFO],
        }
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Layer 3 Audit Engine v1.1.0")
    parser.add_argument("input_json", help="Path to Layer 2 output JSON")
    parser.add_argument("--output", "-o", default=None, help="Path to save audit result JSON")
    args = parser.parse_args()

    with open(args.input_json) as fh:
        doc = json.load(fh)
    result = run_audit(doc)
    print(json.dumps(result, indent=2))
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result, fh, indent=2)
        print(f"\n Saved to: {args.output}")