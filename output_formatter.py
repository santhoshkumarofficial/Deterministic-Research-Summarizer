import json
import os
from datetime import datetime
from pathlib import Path


def format_output(doc: dict, audit_result: dict, reasoning_result: dict) -> dict:
    metadata = doc.get("metadata", {})
    score    = audit_result.get("score", {})
    summary  = audit_result.get("summary", {})

    return {
        "output_metadata": {
            "filename":       metadata.get("filename", "unknown"),
            "total_pages":    metadata.get("total_pages", 0),
            "generated_at":   datetime.utcnow().isoformat() + "Z",
            "formatter_version": "1.0.0",
        },
        "audit": {
            "score":    score.get("score", 0),
            "grade":    score.get("grade", "?"),
            "status":   score.get("status", ""),
            "counts":   score.get("counts", {}),
            "critical": summary.get("critical_issues", []),
            "warnings": summary.get("warnings", []),
            "info":     summary.get("info_notes", []),
        },
        "reasoning": {
            "skipped":         reasoning_result.get("skipped", False),
            # ── Correct keys from reasoning_layer.py ──
            "final_report":    reasoning_result.get("final_report", ""),
            "chunk_summaries": reasoning_result.get("chunk_summaries", {}),
            "model":           reasoning_result.get("model", ""),
            "elapsed_sec":     reasoning_result.get("elapsed_sec", 0),
            # Legacy alias so nothing else breaks
            "summary":         reasoning_result.get("final_report", ""),
        },
        "document": {
            "sections": [
                {
                    "section_id": s.get("section_id"),
                    "title":      s.get("title"),
                    "page_start": s.get("page_start"),
                    "page_end":   s.get("page_end"),
                    "text":       s.get("text", "")[:500],
                }
                for s in doc.get("sections", [])
            ],
            "tables": [
                {
                    "table_id": t.get("table_id"),
                    "page":     t.get("page"),
                    "caption":  t.get("caption"),
                    "headers":  t.get("headers", []),
                    "rows":     t.get("rows", [])[:10],
                }
                for t in doc.get("tables", [])
            ],
            "figures": [
                {
                    "figure_id":        f.get("figure_id"),
                    "page":             f.get("page"),
                    "caption":          f.get("caption"),
                    "semantic_insight": f.get("semantic_insight"),
                }
                for f in doc.get("figures", [])
            ],
            "numbers": doc.get("numbers", [])[:50],
        },
        "qa_context": reasoning_result.get("qa_context", ""),
    }


def save_output(output: dict, results_dir: str, stem: str) -> dict:
    os.makedirs(results_dir, exist_ok=True)

    output_json_path = os.path.join(results_dir, f"{stem}_output.json")
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return {
        "output_json": output_json_path,
    }


def run_output_formatter(doc: dict, audit_result: dict,
                         reasoning_result: dict, results_dir: str, stem: str) -> dict:
    print("\n" + "─" * 60)
    print("  LAYER 5 — Output Formatter")
    print("─" * 60)

    output = format_output(doc, audit_result, reasoning_result)
    paths  = save_output(output, results_dir, stem)

    print(f"  Output JSON saved  ✓  {paths['output_json']}")
    print("─" * 60)

    return output