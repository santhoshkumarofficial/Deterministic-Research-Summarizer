import json
import os
import re
import requests
from pathlib import Path
from datetime import datetime

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL","deepseek-v3.1:671b-cloud")

OLLAMA_CHAT_URL   = f"{OLLAMA_BASE_URL}/v1/chat/completions"   
OLLAMA_MODELS_URL = f"{OLLAMA_BASE_URL}/api/tags"              

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data", "reasoning")
PAPERS_DIR = os.path.join(os.path.dirname(__file__), "data", "papers")

CHUNK_TOKENS     = 900
SYNTHESIS_TOKENS = 3072

os.makedirs(OUTPUT_DIR, exist_ok=True)


def check_ollama():
    """Raise RuntimeError if Ollama is not running or model is missing."""
    try:
        r = requests.get(OLLAMA_MODELS_URL, timeout=5)
        r.raise_for_status()
    except Exception:
        raise RuntimeError(
            f"Ollama is not reachable at {OLLAMA_BASE_URL}. "
            "Run `ollama serve` and try again."
        )

    models = [m["name"] for m in r.json().get("models", [])]
    if not any(m.startswith(OLLAMA_MODEL.split(":")[0]) for m in models):
        raise RuntimeError(
            f"Model '{OLLAMA_MODEL}' not found in Ollama. "
            f"Available: {models}. "
            f"Pull it with: ollama pull {OLLAMA_MODEL}"
        )


def call_ollama(prompt: str, label: str = "", max_tokens: int = CHUNK_TOKENS) -> str:
    tag = f"[{label}] " if label else ""
    print(f"{tag}Sending to Ollama ({OLLAMA_MODEL})...")

    payload = {
        "model":       OLLAMA_MODEL,
        "max_tokens":  max_tokens,
        "temperature": 0.05,
        "top_p":       0.9,
        "stream":      False,
        "messages":    [{"role": "user", "content": prompt}],
    }

    try:
        r = requests.post(
            OLLAMA_CHAT_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=600,  
        )
        r.raise_for_status()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Ollama not reachable at {OLLAMA_BASE_URL}. Is `ollama serve` running?"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama timed out [{label}]")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP error: {e} — {r.text}")

    data     = r.json()
    response = data["choices"][0]["message"]["content"].strip()
    usage    = data.get("usage", {})
    print(f"{tag}Done. ({usage.get('completion_tokens', '?')} tokens)\n")
    return response


_RULES = """STRICT RULES:
1. Every number, percentage, metric, model name, and dataset name MUST appear EXACTLY as in the source. Never round or omit.
2. Write plain academic English paragraphs. No bullet points. No markdown.
3. Never add information absent from the source text."""


def _section(unified: dict, *kws) -> str:
    for sec in unified.get("sections", []):
        h = sec.get("heading", sec.get("title", "")).lower()
        if any(k in h for k in kws):
            return sec.get("text", "").strip()
    return ""


def _sections(unified: dict, *kws) -> str:
    out = []
    for sec in unified.get("sections", []):
        h = sec.get("heading", sec.get("title", "")).lower()
        if any(k in h for k in kws):
            t = sec.get("text", "").strip()
            if t:
                heading = sec.get("heading", sec.get("title", ""))
                out.append(f"[{heading}]\n{t}")
    return "\n\n".join(out)


def _fmt_figures(unified: dict) -> str:
    lines = []
    for fig in unified.get("figures", []):
        cap     = (fig.get("caption") or fig.get("caption_text") or "").strip()
        insight = (fig.get("semantic_insight") or fig.get("primary_insight") or "").strip()
        fid     = fig.get("figure_id") or fig.get("figure_index", "?")
        page    = fig.get("page", "?")
        ftype   = fig.get("figure_type", "unknown")
        lines.append(
            f"Figure {fid} (p{page}, {ftype}):\n"
            f"  Caption : {cap[:250] or 'none'}\n"
            f"  Insight : {insight[:250] or 'none'}"
        )
    return "\n".join(lines) or "No figures."


def _fmt_tables(unified: dict) -> str:
    lines = []
    for tbl in unified.get("tables", []):
        cols = tbl.get("columns", tbl.get("headers", []))
        rows = tbl.get("rows", [])
        tid  = tbl.get("table_id") or tbl.get("table_index", "?")
        page = tbl.get("page", "?")
        cap  = tbl.get("caption", "").strip()
        lines.append(
            f"Table {tid} (p{page}){': ' + cap if cap else ''}:\n"
            f"  Columns: {cols}"
        )
        for row in rows[:4]:
            lines.append(f"  Row    : {row}")
    return "\n".join(lines) or "No tables."


def _fmt_numbers(unified: dict, cap: int = 35) -> str:
    seen, out = set(), []
    for n in unified.get("numbers", []):
        raw = str(n.get("raw", n.get("value", ""))).strip()
        ctx = n.get("context", "").strip()
        if re.match(r'^\d$', raw):
            continue
        if raw not in seen:
            seen.add(raw)
            out.append(f"  {raw:>14}  →  \"{ctx}\"")
        if len(out) >= cap:
            break
    return "\n".join(out) or "No key numbers."


def _p_abstract(u):
    text = _section(u, "abstract")
    if not text:
        text = (u.get("pages") or [{}])[0].get("text", "N/A")[:600]
    return (
        f"{_RULES}\n\nSummarise the ABSTRACT in 3-5 sentences.\n"
        f"Cover: problem solved, proposed approach, key claimed result.\n\n"
        f"ABSTRACT:\n{text[:2200]}\n\nSummary:"
    )


def _p_introduction(u):
    text = _section(u, "introduction")
    return (
        f"{_RULES}\n\nSummarise the INTRODUCTION in 3-5 sentences.\n"
        f"Cover: motivation, research gap, paper scope.\n\n"
        f"INTRODUCTION:\n{(text or 'Not available.')[:2200]}\n\nSummary:"
    )


def _p_methods(u):
    text = _sections(u, "method", "methodology", "approach", "model",
                     "architecture", "framework", "proposed", "system")
    return (
        f"{_RULES}\n\nSummarise the METHODOLOGY in 4-6 sentences.\n"
        f"Cover: technique proposed, how it works, datasets used, training setup.\n"
        f"Preserve all model names, hyperparameters, dataset sizes exactly.\n\n"
        f"METHODOLOGY:\n{(text or 'Not available.')[:2400]}\n\nSummary:"
    )


def _p_results_text(u):
    text = _sections(u, "result", "experiment", "evaluation",
                     "performance", "comparison", "benchmark")
    return (
        f"{_RULES}\n\nSummarise the RESULTS in 5-7 sentences.\n"
        f"Cover: which models were compared, which datasets were used, exact scores and metrics.\n"
        f"You MUST reproduce every number exactly — do not round, omit, or paraphrase any value.\n\n"
        f"RESULTS:\n{(text or 'Not available.')[:1800]}\n\nSummary:"
    )


def _p_results_data(u):
    return (
        f"{_RULES}\n\nWrite a 4-6 sentence DATA SUMMARY covering figures, tables, and key numbers.\n"
        f"Reference each by ID (e.g. \"Table tbl_2 shows...\").\nEvery number must appear exactly.\n\n"
        f"FIGURES:\n{_fmt_figures(u)}\n\nTABLES:\n{_fmt_tables(u)}\n\n"
        f"KEY NUMBERS:\n{_fmt_numbers(u)}\n\nData summary:"
    )


def _p_conclusion(u):
    text = _sections(u, "conclusion", "discussion", "future", "limitation")
    return (
        f"{_RULES}\n\nSummarise the CONCLUSION in 3-5 sentences.\n"
        f"Cover: what was achieved, limitations stated, future work proposed.\n\n"
        f"CONCLUSION:\n{(text or 'Not available.')[:2200]}\n\nSummary:"
    )


def _p_synthesis(chunks, u):
    s = u.get("stats", {})
    return f"""{_RULES}

You are a senior research analyst. Combine the six section summaries below into one complete, detailed research paper report.

CRITICAL: Every number, percentage, score, model name, metric, and dataset name from the summaries MUST appear in the final report — nothing dropped or rounded.

Use exactly these five headings on their own line, paragraph immediately below:

PAPER OVERVIEW
KEY CONTRIBUTIONS
METHODOLOGY
RESULTS AND PERFORMANCE
CONCLUSION AND FUTURE WORK

4-6 sentences per section. No bullet points. No markdown.

Stats: {s.get('total_pages','?')}pp | {s.get('total_figures','?')} figures | {s.get('total_tables','?')} tables

--- ABSTRACT ---
{chunks.get('abstract','N/A')}

--- INTRODUCTION ---
{chunks.get('introduction','N/A')}

--- METHODS ---
{chunks.get('methods','N/A')}

--- RESULTS TEXT ---
{chunks.get('results_text','N/A')}

--- DATA (figures, tables, numbers) ---
{chunks.get('results_data','N/A')}

--- CONCLUSION ---
{chunks.get('conclusion','N/A')}

Final report:"""


def run_reasoning(unified: dict) -> dict:
    paper_id = unified.get("paper_id", "unknown")
    started  = datetime.now()

    print("=" * 60)
    print("REASONING LAYER  —  Layer 4 (Local Ollama)")
    print("=" * 60)
    print(f"Paper  : {paper_id}")
    print(f"Model  : {OLLAMA_MODEL}")
    print(f"Host   : {OLLAMA_BASE_URL}")
    print(f"Started: {started.strftime('%H:%M:%S')}\n")

    check_ollama()

    chunks = {}
    errors = {}

    def run_chunk(key, label, prompt_fn, tok=CHUNK_TOKENS):
        print(f"{'─'*44}")
        print(f"CHUNK — {label}")
        print(f"{'─'*44}")
        try:
            chunks[key] = call_ollama(prompt_fn(), label, max_tokens=tok)
        except Exception as e:
            errors[key] = str(e)
            chunks[key] = f"[{label} failed: {e}]"
            print(f"[WARN] {label}: {e}\n")

    run_chunk("abstract",     "ABSTRACT",     lambda: _p_abstract(unified))
    run_chunk("introduction", "INTRODUCTION", lambda: _p_introduction(unified))
    run_chunk("methods",      "METHODS",      lambda: _p_methods(unified))
    run_chunk("results_text", "RESULTS TEXT", lambda: _p_results_text(unified))
    run_chunk("results_data", "RESULTS DATA", lambda: _p_results_data(unified))
    run_chunk("conclusion",   "CONCLUSION",   lambda: _p_conclusion(unified))

    print(f"{'─'*44}")
    print("SYNTHESIS — Final Report")
    print(f"{'─'*44}")
    try:
        final_report = call_ollama(
            _p_synthesis(chunks, unified),
            "SYNTHESIS",
            max_tokens=SYNTHESIS_TOKENS,
        )
    except Exception as e:
        errors["synthesis"] = str(e)
        final_report = _fallback(chunks, unified)
        print(f"[WARN] Synthesis failed, using fallback: {e}\n")

    elapsed = round((datetime.now() - started).total_seconds(), 1)

    result = {
        "paper_id":        paper_id,
        "model":           OLLAMA_MODEL,
        "generated_at":    datetime.now().isoformat(),
        "elapsed_sec":     elapsed,
        "final_report":    final_report,
        "chunk_summaries": {k: chunks.get(k, "") for k in
                            ("abstract", "introduction", "methods",
                             "results_text", "results_data", "conclusion")},
        "errors": errors,
    }

    _save(paper_id, result)
    _print(result)
    return result


def _fallback(chunks, unified):
    pid = unified.get("paper_id", "Unknown")
    return "\n\n".join([
        f"RESEARCH PAPER SUMMARY — {pid}",
        "PAPER OVERVIEW\n"             + chunks.get("abstract",     "N/A"),
        "KEY CONTRIBUTIONS\n"          + chunks.get("introduction", "N/A"),
        "METHODOLOGY\n"                + chunks.get("methods",      "N/A"),
        "RESULTS AND PERFORMANCE\n"    + chunks.get("results_text", "N/A")
                                       + "\n\n" + chunks.get("results_data", ""),
        "CONCLUSION AND FUTURE WORK\n" + chunks.get("conclusion",   "N/A"),
    ])


def _save(paper_id, result):
    txt  = os.path.join(OUTPUT_DIR, f"{paper_id}_reasoning.txt")
    jout = os.path.join(OUTPUT_DIR, f"{paper_id}_reasoning.json")

    with open(txt, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("RESEARCH PAPER REASONING REPORT\n")
        f.write(f"Paper    : {result['paper_id']}\n")
        f.write(f"Model    : {result['model']}\n")
        f.write(f"Generated: {result['generated_at']}\n")
        f.write(f"Time     : {result['elapsed_sec']}s\n")
        f.write("=" * 70 + "\n\n")
        f.write(result["final_report"])
        f.write("\n")
        if result["errors"]:
            f.write("\n" + "─" * 70 + "\n")
            f.write("PROCESSING WARNINGS:\n")
            for k, v in result["errors"].items():
                f.write(f"  [{k}] {v}\n")

    with open(jout, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n[OUTPUT] Text  → {txt}")
    print(f"[OUTPUT] JSON  → {jout}")


def _print(result):
    print("\n" + "=" * 60)
    print("FINAL REASONING REPORT")
    print("=" * 60)
    print(result["final_report"])
    print("=" * 60)
    print(f"Total time : {result['elapsed_sec']}s")
    if result["errors"]:
        print(f"Warnings   : {len(result['errors'])} chunk(s) — see JSON")
    print("=" * 60)


def run_reasoning_from_json(json_path: str) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return run_reasoning(json.load(f))


if __name__ == "__main__":
    papers = list(Path(PAPERS_DIR).glob("*.json"))
    if not papers:
        raise FileNotFoundError(f"No paper JSON in {PAPERS_DIR}. Run Layer 2 first.")
    latest = max(papers, key=lambda p: p.stat().st_mtime)
    print(f"[INIT] Loading: {latest}\n")
    run_reasoning_from_json(str(latest))