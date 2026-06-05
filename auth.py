"""
auth.py — JWT-based authentication for ResearchAI.

All auth logic lives here.  main.py imports from this module;
it does NOT duplicate these functions.

Token lifetime: 72 h (configurable via TOKEN_TTL_HOURS env var).
JWT payload: {"sub": user_id, "username": username, "exp": ...}
get_current_user returns: {"id": user_id, "username": username}
"""

import os
import uuid
import bcrypt
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from fastapi import HTTPException, Header, Query, Depends

from database import get_db

SECRET  = os.getenv("JWT_SECRET", "changeme_set_a_long_random_string_in_env")
ALG     = "HS256"
EXPIRES = int(os.getenv("TOKEN_TTL_HOURS", "72"))


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def make_token(user_id: str, username: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=EXPIRES)
    return jwt.encode(
        {"sub": user_id, "username": username, "exp": exp},
        SECRET,
        algorithm=ALG,
    )


def _decode(token: str) -> dict:
    """Decode JWT and return {"id": ..., "username": ...}.  Raises 401 on failure."""
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALG])
        return {"id": payload["sub"], "username": payload["username"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── FastAPI dependency: standard Bearer header ────────────────────────────────

def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed token")
    return _decode(authorization.split(" ", 1)[1])


# ── FastAPI dependency: Bearer header OR ?token= query param ─────────────────
# EventSource / SSE cannot set headers, so it passes the token as a query param.

def get_current_user_flexible(
    authorization: str = Header(None),
    token: Optional[str] = Query(None),
) -> dict:
    raw = token
    if not raw and authorization and authorization.startswith("Bearer "):
        raw = authorization.split(" ", 1)[1]
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    return _decode(raw)


# ── Register / Login ──────────────────────────────────────────────────────────

def register_user(username: str, password: str, display_name: str = "") -> dict:
    username = username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Username already taken")
            uid   = str(uuid.uuid4())
            dname = display_name.strip() or username
            cur.execute(
                "INSERT INTO users (id, username, password_hash, display_name) VALUES (%s,%s,%s,%s)",
                (uid, username, hash_password(password), dname),
            )
        db.commit()
    finally:
        db.close()

    return {
        "user_id":      uid,
        "username":     username,
        "display_name": dname,
        "token":        make_token(uid, username),
    }


def login_user(username: str, password: str) -> dict:
    username = username.strip()
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        with db.cursor() as cur:
            cur.execute("UPDATE users SET last_seen = NOW() WHERE id = %s", (row["id"],))
        db.commit()
    finally:
        db.close()

    return {
        "user_id":      row["id"],
        "username":     row["username"],
        "display_name": row.get("display_name", ""),
        "token":        make_token(row["id"], row["username"]),
    }