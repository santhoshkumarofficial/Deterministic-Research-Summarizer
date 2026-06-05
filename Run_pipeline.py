import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime

PDF_PATH = r"C:\projects\research_ai\sample.pdf"

THIS_DIR      = os.path.dirname(os.path.abspath(__file__))
EXTRACTOR_DIR = os.path.join(THIS_DIR, "..")
OUTPUT_DIR    = os.path.join(THIS_DIR, "results")
os.makedirs(OUTPUT_DIR, exist_ok=True)

sys.path.insert(0, THIS_DIR)
sys.path.insert(0, EXTRACTOR_DIR)


print("\n" + "═" * 60)
print("  RESEARCH AI PIPELINE  —  Starting...")
print("═" * 60)

try:
    from text_extractor import extract_paper
    print("  Layer 2 (text_extractor) loaded")
except ImportError as e:
    print(f"  Could not import text_extractor.py: {e}")
    print(f"    Expected location: {EXTRACTOR_DIR}")
    sys.exit(1)

try:
    from reasoning_layer import run_reasoning
    print("  Layer 4 (reasoning_layer / Ollama) loaded")
except ImportError as e:
    print(f"  Could not import reasoning_layer.py: {e}")
    sys.exit(1)

try:
    from audit_engine     import run_audit
    from report_generator import generate_report
    print("  Layer 3 (audit_engine, report_generator) loaded")
    HAS_AUDIT = True
except ImportError as e:
    print(f"  Could not import audit modules: {e}")
    HAS_AUDIT = False

if not os.path.exists(PDF_PATH):
    print(f"\n  PDF not found: {PDF_PATH}")
    print("    Edit PDF_PATH at the top of this file.")
    sys.exit(1)

print(f"\n  PDF : {PDF_PATH}")
print(f"  Out : {OUTPUT_DIR}\n")


print("─" * 60)
print("  LAYER 2 — Extraction")
print("─" * 60)

raw = extract_paper(PDF_PATH)

print("\n  Bridging Layer 2 → Layer 3 schema...")

paper_id    = raw.get("paper_id", Path(PDF_PATH).stem)
stats       = raw.get("stats", {})
total_pages = stats.get("total_pages", 0)

metadata = {
    "filename":              os.path.basename(PDF_PATH),
    "total_pages":           total_pages,
    "extraction_timestamp":  datetime.utcnow().isoformat() + "Z",
    "extractor_version":     "2.0.0",
}


raw_sections  = raw.get("sections", [])
norm_sections = []
for i, sec in enumerate(raw_sections):
    page      = sec.get("page", 1)
    next_page = raw_sections[i + 1].get("page", page) if i + 1 < len(raw_sections) else page
    norm_sections.append({
        "section_id": f"sec_{i+1}",
        "title":      sec.get("heading", f"Section {i+1}"),
        "page_start": page,
        "page_end":   max(page, next_page - 1) if next_page > page else page,
        "text":       sec.get("text", ""),
    })


def _sec_ref(page):
    ref = "sec_1"
    for sec in reversed(norm_sections):
        if sec["page_start"] <= page:
            ref = sec["section_id"]
            break
    return ref


raw_tables  = raw.get("tables", [])
norm_tables = []
for i, tbl in enumerate(raw_tables):
    tbl_page = tbl.get("page", 1)
    norm_tables.append({
        "table_id":    f"tbl_{i+1}",
        "page":        tbl_page,
        "caption":     tbl.get("caption", ""),
        "headers":     tbl.get("columns", []),
        "rows":        tbl.get("rows", []),
        "section_ref": _sec_ref(tbl_page),
    })

raw_figures  = raw.get("figures", [])
norm_figures = []
for i, fig in enumerate(raw_figures):
    fig_page = fig.get("page_number", fig.get("page", 1))
    norm_figures.append({
        "figure_id":        fig.get("figure_id", f"fig_{i+1}"),
        "page":             fig_page,
        "caption":          fig.get("caption_text", fig.get("caption", "")),
        "semantic_insight": fig.get("primary_insight", fig.get("semantic_insight", "")),
        "section_ref":      _sec_ref(fig_page),
    })

raw_numbers  = raw.get("numbers", [])
norm_numbers = []
num_id       = 1


def _parse_value(raw_str):
    try:
        clean = re.sub(r'[,%]', '', str(raw_str))
        if re.search(r'e[-+]?\d+', clean, re.I):
            return float(clean)
        return float(clean)
    except Exception:
        return None


def _parse_unit(raw_str):
    if "%" in str(raw_str):
        return "%"
    for suffix in ["k", "K", "M", "B"]:
        if str(raw_str).endswith(suffix):
            return suffix
    return ""


for num in raw_numbers:
    raw_val = num.get("raw", "")
    value   = _parse_value(raw_val)
    if value is None:
        continue
    num_page = num.get("page", 1)
    norm_numbers.append({
        "number_id":   f"num_{num_id}",
        "value":       value,
        "unit":        _parse_unit(raw_val),
        "context":     num.get("context", ""),
        "page":        num_page,
        "section_ref": _sec_ref(num_page),
    })
    num_id += 1

doc = {
    "paper_id": paper_id,
    "metadata": metadata,
    "sections": norm_sections,
    "tables":   norm_tables,
    "figures":  norm_figures,
    "numbers":  norm_numbers,
    "stats":    stats,
}

print(f"  {len(norm_sections)} sections  |  "
      f"{len(norm_tables)} tables  |  "
      f"{len(norm_figures)} figures  |  "
      f"{len(norm_numbers)} numbers")


print("\n" + "─" * 60)
print("  LAYER 3 — Audit & Validation")
print("─" * 60)

audit_result = None
if HAS_AUDIT:
    audit_result = run_audit(doc)
    score        = audit_result["score"]
    print(f"\n  Score  : {score['score']:.1f}/100")
    print(f"  Grade  : {score['grade']}  —  {score['status']}")
    counts = score["counts"]
    print(f"  {counts.get('CRITICAL', 0)} critical  "
          f" {counts.get('WARNING', 0)} warnings  "
          f" {counts.get('INFO', 0)} info  "
          f" {counts.get('PASS', 0)} pass")
    for f in audit_result["summary"].get("critical_issues", []):
        print(f"   [{f['check_id']}] {f['message']}")
        if f.get("location"):
            print(f"     {f['location']}")
else:
    print("  Skipped (audit_engine not available).")


print("\n" + "─" * 60)
print("  LAYER 4 — Reasoning (Local Ollama)")
print("─" * 60)

reasoning_result = run_reasoning(doc)


stem = paper_id

bridge_path = os.path.join(OUTPUT_DIR, f"{stem}_normalized.json")
with open(bridge_path, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)

if audit_result:
    audit_json_path = os.path.join(OUTPUT_DIR, f"{stem}_audit.json")
    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(audit_result, f, indent=2, ensure_ascii=False)

    if HAS_AUDIT:
        report_md   = generate_report(audit_result)
        report_path = os.path.join(OUTPUT_DIR, f"{stem}_audit_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)


print("\n" + "═" * 60)
print("  PIPELINE COMPLETE")
print("═" * 60)
print(f"  Normalized JSON : {bridge_path}")
if audit_result:
    print(f"  Audit JSON      : {audit_json_path}")
    if HAS_AUDIT:
        print(f"  Audit Report    : {report_path}")

if audit_result:
    score_val = audit_result["score"]["score"]
    if score_val >= 75:
        print(f"\n  Score {score_val:.0f}/100 — READY for Layer 4\n")
    else:
        print(f"\n  Score {score_val:.0f}/100 — Fix issues before Layer 4\n")
        if HAS_AUDIT:
            print(f"  Open the audit report for details:\n  {report_path}\n")
else:
    print("\n  Audit skipped — reasoning ran directly.\n")