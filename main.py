"""
main.py — ResearchAI FastAPI backend  (v3.1 — fully fixed)

Changes from original:
  * Auth unified: removed duplicate hash/token/user functions, now imports from auth.py
  * user_sessions table removed — JWT is stateless, no DB lookup per request
  * text_extractor import wrapped in try/except (no startup crash if missing)
  * /api/chat uses chat_engine.stream_chat via a thread-pool wrapper so the
    async event loop is never blocked by synchronous DB / HTTP calls
  * /api/status uses get_current_user_flexible (Bearer header OR ?token=)
  * All datetime objects serialised before returning JSON
  * /api/auth/me fetches display_name from DB using JWT payload's user_id
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

import json
import uuid
import asyncio
import shutil
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator, Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import get_db
from auth import (
    get_current_user,
    get_current_user_flexible,
    register_user,
    login_user,
)
from chat_engine import stream_chat as _engine_stream_chat

# ── Optional pipeline modules (guarded so startup never crashes) ──────────────
try:
    from text_extractor import extract_paper
    HAS_EXTRACTOR = True
except ImportError:
    HAS_EXTRACTOR = False

try:
    from reasoning_layer import run_reasoning
    HAS_REASONING = True
except ImportError:
    HAS_REASONING = False

try:
    from audit_engine import run_audit
    HAS_AUDIT = True
except ImportError:
    HAS_AUDIT = False

try:
    from output_formatter import run_output_formatter
    HAS_FORMATTER = True
except ImportError:
    HAS_FORMATTER = False

try:
    from report_generator import generate_report
    HAS_REPORT_GEN = True
except ImportError:
    HAS_REPORT_GEN = False

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "deepseek-v3.1:671b-cloud")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"

BASE_DIR    = Path(__file__).parent
TEMP_DIR    = BASE_DIR / "temp_uploads"
RESULTS_DIR = BASE_DIR / "results"
STATIC_DIR  = BASE_DIR / "static"

for _d in (TEMP_DIR, RESULTS_DIR, STATIC_DIR):
    _d.mkdir(exist_ok=True)

# In-memory job tracker (pipeline runs are in-process async tasks)
jobs: dict = {}

# Thread pool for running sync blocking code without blocking the event loop
_executor = ThreadPoolExecutor(max_workers=4)

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="ResearchAI", version="3.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── DB convenience helpers ────────────────────────────────────────────────────

def db_one(sql: str, args=()) -> Optional[dict]:
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(sql, args)
            return c.fetchone()
    finally:
        conn.close()


def db_all(sql: str, args=()) -> list:
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(sql, args)
            return c.fetchall()
    finally:
        conn.close()


def db_exec(sql: str, args=()):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def db_exec_many(statements: list):
    """Run multiple (sql, args) pairs in one transaction."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            for sql, args in statements:
                c.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _ser(obj):
    """Serialise a row dict — convert datetime objects to ISO strings."""
    out = {}
    for k, v in obj.items():
        out[k] = v.isoformat() if isinstance(v, datetime) else v
    return out


# ── Pydantic request models ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username:     str
    password:     str
    display_name: str = ""

class LoginRequest(BaseModel):
    username: str
    password: str

class SessionCreate(BaseModel):
    name:     str
    filename: str
    job_id:   str

class ChatRequest(BaseModel):
    message:    str
    session_id: str

class RenameSession(BaseModel):
    name: str


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _build_qa_context(doc: dict, reasoning_result: dict) -> str:
    parts = []
    for sec in doc.get("sections", []):
        title = sec.get("title", sec.get("heading", ""))
        text  = sec.get("text", "").strip()
        if text:
            parts.append(f"[SECTION: {title}]\n{text}")
    for tbl in doc.get("tables", []):
        tid   = tbl.get("table_id", "?")
        cols  = tbl.get("headers", tbl.get("columns", []))
        cap   = tbl.get("caption", "").strip()
        block = f"[TABLE {tid}{': ' + cap if cap else ''}]\nColumns: {cols}"
        for row in tbl.get("rows", [])[:3]:
            block += f"\nRow: {row}"
        parts.append(block)
    for fig in doc.get("figures", []):
        fid     = fig.get("figure_id", "?")
        cap     = (fig.get("caption") or "").strip()
        insight = (fig.get("semantic_insight") or "").strip()
        if cap or insight:
            parts.append(f"[FIGURE {fid}]\nCaption: {cap}\nInsight: {insight}")
    final_report = reasoning_result.get("final_report", "")
    if final_report:
        parts.append(f"[REASONING SUMMARY]\n{final_report}")
    full = "\n\n".join(parts)
    return (full[:14000] + "\n...[truncated]") if len(full) > 14000 else full


def _bridge_schema(raw: dict, pdf_path: str) -> dict:
    stats       = raw.get("stats", {})
    total_pages = stats.get("total_pages", 0)
    metadata = {
        "filename":             os.path.basename(pdf_path),
        "total_pages":          total_pages,
        "extraction_timestamp": datetime.utcnow().isoformat() + "Z",
        "extractor_version":    "2.0.0",
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
        for s in reversed(norm_sections):
            if s["page_start"] <= page:
                ref = s["section_id"]
                break
        return ref

    def _parse_value(raw_str):
        try:
            return float(re.sub(r"[,%]", "", str(raw_str)))
        except Exception:
            return None

    def _parse_unit(raw_str):
        if "%" in str(raw_str):
            return "%"
        for s in ["k", "K", "M", "B"]:
            if str(raw_str).endswith(s):
                return s
        return ""

    norm_tables, norm_figures, norm_numbers = [], [], []
    num_id = 1

    for i, tbl in enumerate(raw.get("tables", [])):
        p = tbl.get("page", 1)
        norm_tables.append({
            "table_id":   f"tbl_{i+1}", "page": p,
            "caption":    tbl.get("caption", ""),
            "headers":    tbl.get("columns", []),
            "rows":       tbl.get("rows", []),
            "section_ref": _sec_ref(p),
        })

    for i, fig in enumerate(raw.get("figures", [])):
        p = fig.get("page_number", fig.get("page", 1))
        norm_figures.append({
            "figure_id":        fig.get("figure_id", f"fig_{i+1}"), "page": p,
            "caption":          fig.get("caption_text", fig.get("caption", "")),
            "semantic_insight": fig.get("primary_insight", fig.get("semantic_insight", "")),
            "section_ref":      _sec_ref(p),
        })

    for num in raw.get("numbers", []):
        raw_val = num.get("raw", "")
        value   = _parse_value(raw_val)
        if value is None:
            continue
        p = num.get("page", 1)
        norm_numbers.append({
            "number_id":  f"num_{num_id}", "value": value,
            "unit":       _parse_unit(raw_val), "context": num.get("context", ""),
            "page":       p, "section_ref": _sec_ref(p),
        })
        num_id += 1

    return {
        "paper_id": raw.get("paper_id", Path(pdf_path).stem),
        "metadata": metadata,
        "sections": norm_sections,
        "tables":   norm_tables,
        "figures":  norm_figures,
        "numbers":  norm_numbers,
        "stats":    stats,
    }


def _stub_formatter(doc, audit_result, reasoning_result, stem) -> dict:
    qa_context    = _build_qa_context(doc, reasoning_result)
    audit_score   = (audit_result or {}).get("score",   {})
    audit_summary = (audit_result or {}).get("summary", {})
    return {
        "output_metadata": {
            "filename":          doc.get("metadata", {}).get("filename", stem),
            "total_pages":       doc.get("metadata", {}).get("total_pages", 0),
            "generated_at":      datetime.utcnow().isoformat() + "Z",
            "formatter_version": "3.1.0",
        },
        "audit": {
            "score":    audit_score.get("score", 0),
            "grade":    audit_score.get("grade", "?"),
            "status":   audit_score.get("status", ""),
            "counts":   audit_score.get("counts", {}),
            "critical": audit_summary.get("critical_issues", []),
            "warnings": audit_summary.get("warnings", []),
            "info":     audit_summary.get("info_notes", []),
        },
        "reasoning": {
            "skipped":         not HAS_REASONING,
            "final_report":    reasoning_result.get("final_report", ""),
            "chunk_summaries": reasoning_result.get("chunk_summaries", {}),
            "model":           reasoning_result.get("model", ""),
            "elapsed_sec":     reasoning_result.get("elapsed_sec", 0),
        },
        "document": {
            "sections": doc.get("sections", []),
            "tables":   doc.get("tables",   []),
            "figures":  doc.get("figures",  []),
            "numbers":  doc.get("numbers",  []),
        },
        "qa_context": qa_context,
    }


# ── Async pipeline runner ─────────────────────────────────────────────────────

async def run_pipeline(job_id: str, pdf_path: str, user_id: str):
    job  = jobs[job_id]
    loop = asyncio.get_event_loop()

    try:
        job["status"] = "running"; job["progress"] = 5

        if not HAS_EXTRACTOR:
            raise RuntimeError("text_extractor.py not found — cannot process PDF")
        if not HAS_REASONING:
            raise RuntimeError("reasoning_layer.py not found — cannot run reasoning")

        job["log"].append("Layer 2: Extracting paper…")
        job["progress"] = 10
        raw = await loop.run_in_executor(_executor, extract_paper, pdf_path)
        job["log"].append(
            f"Extraction done: {len(raw.get('sections',[]))} sections, "
            f"{len(raw.get('figures',[]))} figures, {len(raw.get('tables',[]))} tables."
        )

        job["progress"] = 25
        job["log"].append("Normalising schema…")
        doc = _bridge_schema(raw, pdf_path)

        job["progress"] = 40
        audit_result = None
        if HAS_AUDIT:
            job["log"].append("Layer 3: Running audit…")
            audit_result = await loop.run_in_executor(_executor, run_audit, doc)
            sc = audit_result.get("score", {})
            job["log"].append(f"Audit done: {sc.get('score', 0):.1f}/100 ({sc.get('grade','?')})")
        else:
            job["log"].append("Layer 3: audit_engine not available, skipping.")

        job["progress"] = 60
        job["log"].append(f"Layer 4: Reasoning via Ollama ({OLLAMA_MODEL})…")
        reasoning_result = await loop.run_in_executor(_executor, run_reasoning, doc)
        job["log"].append("Reasoning done.")

        job["progress"] = 80
        job["log"].append("Layer 5: Formatting output…")
        stem = doc.get("paper_id", Path(pdf_path).stem)

        if HAS_FORMATTER:
            output = await loop.run_in_executor(
                _executor, run_output_formatter,
                doc, audit_result, reasoning_result, str(RESULTS_DIR), stem,
            )
            output_path = str(RESULTS_DIR / f"{stem}_output.json")
            # Ensure qa_context is present (output_formatter may not build it)
            if not output.get("qa_context"):
                output["qa_context"] = _build_qa_context(doc, reasoning_result)
            # Ensure reasoning keys are correct
            rsn = output.setdefault("reasoning", {})
            if not rsn.get("final_report"):
                rsn["final_report"]    = reasoning_result.get("final_report", "")
                rsn["chunk_summaries"] = reasoning_result.get("chunk_summaries", {})
                rsn["model"]           = reasoning_result.get("model", "")
                rsn["elapsed_sec"]     = reasoning_result.get("elapsed_sec", 0)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(output, fh, indent=2, ensure_ascii=False)
        else:
            output      = _stub_formatter(doc, audit_result, reasoning_result, stem)
            output_path = str(RESULTS_DIR / f"{stem}_output.json")
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(output, fh, indent=2, ensure_ascii=False)

        report_md = (
            generate_report(audit_result)
            if HAS_REPORT_GEN and audit_result
            else f"# Report: {stem}\n\nAudit engine not available.\n"
        )
        report_path = str(RESULTS_DIR / f"{stem}_audit_report.md")
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(report_md)

        # Persist to MySQL
        db_exec(
            """INSERT INTO job_outputs
               (job_id, user_id, filename, stem, output_json, output_path, report_path)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
               output_json=%s, output_path=%s, report_path=%s, stem=%s""",
            (
                job_id, user_id,
                doc.get("metadata", {}).get("filename", stem), stem,
                json.dumps(output), output_path, report_path,
                json.dumps(output), output_path, report_path, stem,
            ),
        )

        job.update({
            "status":      "done", "progress": 100,
            "output":      output, "output_path": output_path,
            "report_path": report_path, "stem": stem,
        })
        job["log"].append("Pipeline complete ✓")

    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["log"].append(f"ERROR: {exc}")
        job["log"].append(traceback.format_exc())


def _get_job_or_404(job_id: str) -> dict:
    if job_id in jobs:
        return jobs[job_id]
    row = db_one("SELECT * FROM job_outputs WHERE job_id = %s", (job_id,))
    if row:
        output = json.loads(row["output_json"])
        jobs[job_id] = {
            "job_id":      job_id,
            "status":      "done",
            "progress":    100,
            "log":         ["Restored from database."],
            "output":      output,
            "output_path": row["output_path"],
            "report_path": row["report_path"],
            "stem":        row["stem"],
        }
        return jobs[job_id]
    raise HTTPException(status_code=404, detail="Job not found")


# ════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    return register_user(req.username, req.password, req.display_name)


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    return login_user(req.username, req.password)


@app.post("/api/auth/logout")
async def logout():
    # JWT is stateless — client just discards the token.
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user=Depends(get_current_user)):
    row = db_one(
        "SELECT id, username, display_name FROM users WHERE id = %s",
        (user["id"],),
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


# ════════════════════════════════════════════════════════════════════════════
#  PIPELINE ROUTES
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted.")
    if not HAS_EXTRACTOR or not HAS_REASONING:
        raise HTTPException(
            status_code=503,
            detail="Pipeline modules (text_extractor / reasoning_layer) not installed.",
        )
    job_id   = str(uuid.uuid4())
    pdf_path = TEMP_DIR / f"{job_id}.pdf"
    with open(pdf_path, "wb") as fh:
        shutil.copyfileobj(file.file, fh)
    jobs[job_id] = {
        "job_id":   job_id,
        "filename": file.filename,
        "status":   "queued",
        "progress": 0,
        "log":      ["PDF received. Pipeline starting…"],
        "output":   None,
    }
    asyncio.create_task(run_pipeline(job_id, str(pdf_path), user["id"]))
    return {"job_id": job_id, "filename": file.filename}


@app.get("/api/status/{job_id}")
async def stream_status(
    job_id: str,
    user=Depends(get_current_user_flexible),   # supports ?token= for EventSource
):
    _get_job_or_404(job_id)  # raises 404 if truly unknown

    async def gen() -> AsyncGenerator[str, None]:
        idx = 0
        while True:
            job      = jobs.get(job_id, {})
            new_logs = job.get("log", [])[idx:]
            for line in new_logs:
                yield f"data: {json.dumps({'log': line, 'progress': job.get('progress', 0), 'status': job.get('status', '')})}\n\n"
            idx += len(new_logs)
            if job.get("status") in ("done", "error"):
                yield f"data: {json.dumps({'log': '__DONE__', 'progress': job.get('progress', 0), 'status': job.get('status', '')})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/results/{job_id}")
async def get_results(job_id: str, user=Depends(get_current_user)):
    job = _get_job_or_404(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail=f"Not ready: {job['status']}")
    return job["output"]


@app.get("/api/recent-job")
async def recent_job(user=Depends(get_current_user)):
    row = db_one(
        "SELECT job_id FROM job_outputs WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
        (user["id"],),
    )
    return {"job_id": row["job_id"] if row else None}


# ════════════════════════════════════════════════════════════════════════════
#  SESSION ROUTES
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/sessions")
async def create_session(req: SessionCreate, user=Depends(get_current_user)):
    # Verify the job belongs to this user
    job_row = db_one(
        "SELECT job_id FROM job_outputs WHERE job_id = %s AND user_id = %s",
        (req.job_id, user["id"]),
    )
    if not job_row:
        raise HTTPException(status_code=404, detail="Job not found or access denied")
    sid = str(uuid.uuid4())
    db_exec(
        "INSERT INTO chat_sessions (id, user_id, job_id, name, filename) VALUES (%s,%s,%s,%s,%s)",
        (sid, user["id"], req.job_id, req.name, req.filename),
    )
    return {"session_id": sid, "name": req.name}


@app.get("/api/sessions")
async def list_sessions(user=Depends(get_current_user)):
    rows = db_all(
        """SELECT s.*,
               (SELECT content FROM messages m
                WHERE m.session_id = s.id
                ORDER BY m.created_at DESC LIMIT 1) AS last_message,
               (SELECT COUNT(*) FROM messages m
                WHERE m.session_id = s.id) AS message_count
           FROM chat_sessions s
           WHERE s.user_id = %s
           ORDER BY s.updated_at DESC""",
        (user["id"],),
    )
    return [_ser(dict(r)) for r in rows]


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, user=Depends(get_current_user)):
    db_exec_many([
        ("DELETE FROM messages     WHERE session_id = %s",                    (session_id,)),
        ("DELETE FROM chat_sessions WHERE id = %s AND user_id = %s", (session_id, user["id"])),
    ])
    return {"deleted": session_id}


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSession, user=Depends(get_current_user)):
    db_exec(
        "UPDATE chat_sessions SET name = %s WHERE id = %s AND user_id = %s",
        (req.name, session_id, user["id"]),
    )
    return {"ok": True}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str, user=Depends(get_current_user)):
    rows = db_all(
        """SELECT m.* FROM messages m
           JOIN chat_sessions s ON s.id = m.session_id
           WHERE m.session_id = %s AND s.user_id = %s
           ORDER BY m.created_at ASC""",
        (session_id, user["id"]),
    )
    return [_ser(dict(r)) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
#  CHAT ROUTE  —  streams tokens from Ollama via chat_engine.stream_chat
# ════════════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
async def chat(req: ChatRequest, user=Depends(get_current_user)):
    """
    Stream the LLM's response token by token (SSE).

    chat_engine.stream_chat is a *synchronous* generator that does blocking
    MySQL queries and HTTP calls.  We run it in a thread pool and push each
    yielded chunk into an async queue so the event loop is never blocked.
    """
    # Quick sanity check before starting the thread
    session = db_one(
        "SELECT id FROM chat_sessions WHERE id = %s AND user_id = %s",
        (req.session_id, user["id"]),
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    queue: asyncio.Queue = asyncio.Queue()
    loop  = asyncio.get_event_loop()

    def _run_sync():
        """Run the sync generator in a worker thread, pushing chunks into the queue."""
        try:
            for chunk in _engine_stream_chat(req.session_id, user["id"], req.message):
                # asyncio.Queue is not thread-safe; use call_soon_threadsafe
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as exc:
            err = f'data: {json.dumps({"token": f"[Error: {exc}]"})}\n\n'
            loop.call_soon_threadsafe(queue.put_nowait, err)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    # Start the sync generator in the thread pool
    loop.run_in_executor(_executor, _run_sync)

    async def _generate() -> AsyncGenerator[str, None]:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(_generate(), media_type="text/event-stream")


# ════════════════════════════════════════════════════════════════════════════
#  DOWNLOAD + HEALTH
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/download/{job_id}/json")
async def download_json(job_id: str, user=Depends(get_current_user)):
    job = _get_job_or_404(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not ready.")
    return FileResponse(
        job["output_path"],
        filename=f"{job['stem']}_output.json",
        media_type="application/json",
    )


@app.get("/api/download/{job_id}/report")
async def download_report(job_id: str, user=Depends(get_current_user)):
    job = _get_job_or_404(job_id)
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Job not ready.")
    return FileResponse(
        job["report_path"],
        filename=f"{job['stem']}_audit_report.md",
        media_type="text/markdown",
    )


@app.get("/api/health")
async def health():
    ollama_ok = False
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    db_ok = False
    try:
        db_one("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return {
        "status":      "ok",
        "timestamp":   datetime.utcnow().isoformat() + "Z",
        "db_ok":       db_ok,
        "ollama_ok":   ollama_ok,
        "llm_model":   OLLAMA_MODEL,
        "has_extractor": HAS_EXTRACTOR,
        "has_reasoning": HAS_REASONING,
        "has_audit":     HAS_AUDIT,
        "has_formatter": HAS_FORMATTER,
        "has_report_gen": HAS_REPORT_GEN,
    }




_assets_dir = STATIC_DIR / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    """Serve the React SPA for all non-API paths."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>Build the frontend first: cd frontend && npm run build</h1>",
        status_code=503,
    )