"""
chat_engine.py — Streaming chat against a processed research paper.

Fixes applied vs original:
  1. "FROM sessions"  →  "FROM chat_sessions"  (table was renamed)
  2. Prefers the pre-built qa_context (richer, 14k chars) over re-building
     from raw sections/tables/figures
  3. Updates chat_sessions.updated_at after each turn
  4. Proper chunk decoding: strips whitespace before comparing "[DONE]"
"""

import os
import uuid
import json
import requests

from database import get_db

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL",    "deepseek-v3.1:671b-cloud")
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"


# ── Context builder ───────────────────────────────────────────────────────────

def build_context(output: dict) -> str:
    """
    Build the paper context string sent to the LLM.

    Uses the pre-built qa_context when available (assembled by the pipeline
    and stored in job_outputs.output_json).  Falls back to rebuilding from
    the document sub-keys if qa_context is absent or empty.
    """
    # Prefer the pre-built rich context
    if output.get("qa_context"):
        return output["qa_context"]

    doc   = output.get("document", output)
    parts = []

    for sec in doc.get("sections", []):
        title = sec.get("title", "")
        text  = sec.get("text", "").strip()
        if text:
            parts.append(f"[SECTION: {title}]\n{text}")

    for tbl in doc.get("tables", []):
        tid  = tbl.get("table_id", "")
        cap  = tbl.get("caption", "")
        cols = tbl.get("headers", [])
        block = f"[TABLE {tid}: {cap}]\nColumns: {cols}"
        for row in tbl.get("rows", [])[:3]:
            block += f"\n  Row: {row}"
        parts.append(block)

    for fig in doc.get("figures", []):
        fid     = fig.get("figure_id", "")
        cap     = (fig.get("caption") or "").strip()
        insight = (fig.get("semantic_insight") or "").strip()
        if cap or insight:
            parts.append(f"[FIGURE {fid}]\nCaption: {cap}\nInsight: {insight}")

    # Append reasoning summary if present
    final_report = output.get("reasoning", {}).get("final_report", "")
    if final_report:
        parts.append(f"[REASONING SUMMARY]\n{final_report}")

    full = "\n\n".join(parts)
    return (full[:14000] + "\n...[truncated]") if len(full) > 14000 else full


# ── DB helpers (local, simple) ────────────────────────────────────────────────

def _save_message(session_id: str, role: str, content: str) -> None:
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (id, session_id, role, content) VALUES (%s,%s,%s,%s)",
                (str(uuid.uuid4()), session_id, role, content),
            )
        db.commit()
    finally:
        db.close()


def _touch_session(session_id: str) -> None:
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                (session_id,),
            )
        db.commit()
    finally:
        db.close()


# ── Main streaming function ───────────────────────────────────────────────────

def stream_chat(session_id: str, user_id: str, user_message: str):
    """
    Sync generator — yields SSE-formatted strings.
    Wrap in an async generator when calling from FastAPI:

        async def _gen():
            loop = asyncio.get_event_loop()
            for chunk in stream_chat(...):
                yield chunk

    Steps:
        1. Load session + job from MySQL
        2. Save user message
        3. Fetch history
        4. Stream Ollama response token by token
        5. Save assistant reply + touch session timestamp
    """

    # ── 1. Load session and paper output ─────────────────────────────────────
    db = get_db()
    try:
        with db.cursor() as cur:
            # BUG FIX: was "FROM sessions" — correct table is "chat_sessions"
            cur.execute(
                "SELECT * FROM chat_sessions WHERE id = %s AND user_id = %s",
                (session_id, user_id),
            )
            session = cur.fetchone()

        if not session:
            yield 'data: {"token": "[Error: Session not found or access denied]"}\n\n'
            yield 'data: {"token": "__DONE__"}\n\n'
            return

        with db.cursor() as cur:
            cur.execute(
                "SELECT output_json FROM job_outputs WHERE job_id = %s AND user_id = %s",
                (session["job_id"], user_id),
            )
            job_row = cur.fetchone()
    finally:
        db.close()

    if not job_row:
        yield 'data: {"token": "[Error: Processed paper not found for this session]"}\n\n'
        yield 'data: {"token": "__DONE__"}\n\n'
        return

    output   = json.loads(job_row["output_json"])
    context  = build_context(output)
    filename = output.get("output_metadata", {}).get("filename", "the paper")

    # ── 2. Save user turn ────────────────────────────────────────────────────
    _save_message(session_id, "user", user_message)

    # ── 3. Fetch conversation history ────────────────────────────────────────
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = %s ORDER BY created_at ASC",
                (session_id,),
            )
            history = cur.fetchall()
    finally:
        db.close()

    # ── 4. Build payload and stream ──────────────────────────────────────────
    system_prompt = (
        f"You are an expert academic research assistant analysing the paper '{filename}'.\n\n"
        f"STRICT RULES:\n"
        f"- Answer ONLY using information in the paper content below.\n"
        f"- If something is not in the paper, say: 'This is not mentioned in the paper.'\n"
        f"- Use formal, precise academic English.\n"
        f"- Reference specific sections, tables (by ID), or figures (by ID) when relevant.\n"
        f"- Structure longer answers with clear paragraphs.\n\n"
        f"PAPER CONTENT:\n{context}"
    )

    messages_payload = [{"role": "system", "content": system_prompt}]
    messages_payload += [{"role": r["role"], "content": r["content"]} for r in history]

    full_response = ""
    try:
        with requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model":       OLLAMA_MODEL,
                "messages":    messages_payload,
                "temperature": 0.1,
                "top_p":       0.9,
                "stream":      True,
            },
            stream=True,
            timeout=180,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                chunk_str = decoded[6:].strip()
                if chunk_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(chunk_str)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        full_response += delta
                        yield f"data: {json.dumps({'token': delta})}\n\n"
                except Exception:
                    pass

    except Exception as exc:
        err = f"[LLM Error: {exc}]"
        yield f"data: {json.dumps({'token': err})}\n\n"
        full_response = err

    # ── 5. Persist assistant reply and update session ────────────────────────
    _save_message(session_id, "assistant", full_response)
    _touch_session(session_id)

    yield 'data: {"token": "__DONE__"}\n\n'