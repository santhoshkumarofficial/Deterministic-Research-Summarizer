import React, { useState, useEffect, useRef } from "react";

// ── Theme ──────────────────────────────────────────────────────────────────
const THEMES = {
  dark: {
    bg:        "#0a0b0d",
    bg1:       "#111318",
    bg2:       "#16191f",
    bg3:       "#1c2028",
    bg4:       "#232a36",
    bg5:       "#2a3240",
    border:    "rgba(148,163,184,0.07)",
    border2:   "rgba(148,163,184,0.13)",
    border3:   "rgba(148,163,184,0.22)",
    text0:     "#f0f2f8",
    text1:     "#a8b4cc",
    text2:     "#6878a0",
    text3:     "#384060",
    accent:    "#5b7cf6",
    accentHov: "#7090ff",
    accentBg:  "rgba(91,124,246,0.12)",
    green:     "#4ade80",
    yellow:    "#fbbf24",
    red:       "#f87171",
    shadow:    "0 0 0 1px rgba(148,163,184,0.07), 0 8px 32px rgba(0,0,0,0.6)",
    shadowLg:  "0 0 0 1px rgba(148,163,184,0.10), 0 24px 64px rgba(0,0,0,0.8)",
  },
  light: {
    bg:        "#f8f9fc",
    bg1:       "#ffffff",
    bg2:       "#f1f3f8",
    bg3:       "#e8ecf4",
    bg4:       "#dde3ef",
    bg5:       "#d0d8e8",
    border:    "rgba(30,40,80,0.08)",
    border2:   "rgba(30,40,80,0.13)",
    border3:   "rgba(30,40,80,0.22)",
    text0:     "#0f1629",
    text1:     "#3a4a6a",
    text2:     "#7080a8",
    text3:     "#a0aac0",
    accent:    "#4a6cf0",
    accentHov: "#3a5ce0",
    accentBg:  "rgba(74,108,240,0.10)",
    green:     "#16a34a",
    yellow:    "#d97706",
    red:       "#dc2626",
    shadow:    "0 0 0 1px rgba(30,40,80,0.08), 0 4px 16px rgba(30,40,80,0.08)",
    shadowLg:  "0 0 0 1px rgba(30,40,80,0.10), 0 16px 48px rgba(30,40,80,0.14)",
  },
};

// API base — empty string = same origin (works in dev proxy AND production)
const API = "";

// ── Logo SVG ──────────────────────────────────────────────────────────────
function Logo({ size = 28, t }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="9" fill={t.accent} />
      <path d="M8 10h10M8 14h7M8 18h10M8 22h5" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
      <circle cx="23" cy="21" r="5" fill="none" stroke="white" strokeWidth="1.8"/>
      <path d="M26.5 24.5l2.5 2.5" stroke="white" strokeWidth="1.8" strokeLinecap="round"/>
    </svg>
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────
function Spinner({ t }) {
  return (
    <div style={{
      width: 16, height: 16, borderRadius: "50%",
      border: `2px solid ${t.border3}`,
      borderTopColor: t.accent,
      animation: "spin 0.7s linear infinite",
      display: "inline-block",
    }} />
  );
}

// ── Score ring ────────────────────────────────────────────────────────────
function ScoreRing({ score, t }) {
  const r = 28, c = 2 * Math.PI * r;
  const pct = Math.min(score / 100, 1);
  const color = score >= 75 ? t.green : score >= 50 ? t.yellow : t.red;
  return (
    <svg width="72" height="72" viewBox="0 0 72 72">
      <circle cx="36" cy="36" r={r} fill="none" stroke={t.bg4} strokeWidth="6"/>
      <circle cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="6"
        strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
        strokeLinecap="round" transform="rotate(-90 36 36)"
        style={{ transition: "stroke-dashoffset 1s ease" }}
      />
      <text x="36" y="40" textAnchor="middle" fill={color}
        style={{ fontSize: 14, fontWeight: 700, fontFamily: "inherit" }}>
        {Math.round(score)}
      </text>
    </svg>
  );
}

export default function App() {
  const [theme, setTheme] = useState("dark");
  const t = THEMES[theme];

  const [view, setView]           = useState("login");
  const [authTab, setAuthTab]     = useState("login");
  const [token, setToken]         = useState(() => localStorage.getItem("rai_token") || "");
  const [username, setUsername]   = useState(() => localStorage.getItem("rai_user") || "");

  const [loginForm, setLoginForm]     = useState({ username: "", password: "" });
  const [regForm, setRegForm]         = useState({ username: "", password: "" });
  const [authError, setAuthError]     = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const [uploadProgress, setUploadProgress] = useState(null);
  const [uploadPct, setUploadPct]           = useState(0);
  const [activeJob, setActiveJob]           = useState(null);
  const [sections, setSections]             = useState([]);
  const [reasoning, setReasoning]           = useState("");
  const [auditData, setAuditData]           = useState(null);
  const [expanded, setExpanded]             = useState({});
  const [search, setSearch]                 = useState("");
  const [mainTab, setMainTab]               = useState("sections");
  const [sidebarOpen, setSidebarOpen]       = useState(true);
  const [rightOpen, setRightOpen]           = useState(true);
  const [sessionId, setSessionId]           = useState(null);
  const [chatMessages, setChatMessages]     = useState([]);
  const [chatInput, setChatInput]           = useState("");
  const [streaming, setStreaming]           = useState(false);
  const [appError, setAppError]             = useState("");

  const chatEndRef   = useRef(null);
  const fileInputRef = useRef(null);
  // Ref to active EventSource — lets us close it before starting a new one
  const esRef = useRef(null);

  // ── Inject global CSS ──────────────────────────────────────────────────
  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = `
      @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap');
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { font-family: 'Instrument Sans', sans-serif; background: ${t.bg}; color: ${t.text0}; }
      @keyframes spin    { to { transform: rotate(360deg); } }
      @keyframes fadeUp  { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
      @keyframes shimmer { 0%,100% { opacity:.4; } 50% { opacity:1; } }
      @keyframes slideIn { from { opacity:0; transform:translateX(-8px); } to { opacity:1; transform:translateX(0); } }
      ::selection { background: ${t.accent}33; }
      ::-webkit-scrollbar { width: 3px; height: 3px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: ${t.border3}; border-radius: 2px; }
    `;
    document.head.appendChild(style);
    return () => document.head.removeChild(style);
  }, [theme]);

  // ── Restore session on mount ───────────────────────────────────────────
  useEffect(() => {
    if (token) { setView("app"); loadLastJob(); }
  }, []);

  // ── Auto-scroll chat to bottom ─────────────────────────────────────────
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // ── Auth ───────────────────────────────────────────────────────────────
  async function handleAuth() {
    setAuthError(""); setAuthLoading(true);
    try {
      const endpoint = authTab === "login" ? "/api/auth/login" : "/api/auth/register";
      const form     = authTab === "login" ? loginForm : regForm;
      const r = await fetch(`${API}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const d = await r.json();
      if (!r.ok) { setAuthError(d.detail || "Authentication failed"); return; }
      localStorage.setItem("rai_token", d.token);
      localStorage.setItem("rai_user",  d.username);
      setToken(d.token); setUsername(d.username); setView("app");
    } catch {
      setAuthError("Network error — is the backend running?");
    } finally {
      setAuthLoading(false);
    }
  }

  function logout() {
    if (esRef.current) { esRef.current.close(); esRef.current = null; }
    localStorage.clear();
    setToken(""); setUsername(""); setView("login");
    setActiveJob(null); setSections([]); setChatMessages([]);
    setReasoning(""); setAuditData(null); setSessionId(null);
  }

  // ── Load most recent job for this user ────────────────────────────────
  async function loadLastJob() {
    try {
      const r = await fetch(`${API}/api/recent-job`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const d = await r.json();
        if (d.job_id) await loadJob(d.job_id);
      }
    } catch {}
  }

  // ── Upload PDF ─────────────────────────────────────────────────────────
  async function handleUpload(file) {
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
      setAppError("Please upload a PDF file."); return;
    }
    // Close any previous SSE stream
    if (esRef.current) { esRef.current.close(); esRef.current = null; }

    setAppError("");
    setUploadProgress("Uploading PDF…");
    setUploadPct(5);

    const fd = new FormData();
    fd.append("file", file);

    try {
      const r = await fetch(`${API}/api/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const d = await r.json();
      if (!r.ok) { setAppError(d.detail || "Upload failed"); setUploadProgress(null); return; }
      // ✅ FIX 3: SSE-based real-time status — no page refresh needed
      listenToJob(d.job_id);
    } catch (e) {
      setAppError("Upload error: " + e.message);
      setUploadProgress(null);
    }
  }

  // ── ✅ FIX 3: Real-time SSE job listener ──────────────────────────────
  // Browser EventSource cannot send custom headers, so we pass token as
  // a query param. The backend's _auth_token() dependency already supports
  // this (?token=...) for exactly this reason.
  function listenToJob(jobId) {
    const url = `${API}/api/status/${jobId}?token=${encodeURIComponent(token)}`;
    const es  = new EventSource(url);
    esRef.current = es;

    es.onmessage = async (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }

      // Reflect real backend progress + log messages in the UI
      if (data.progress !== undefined) setUploadPct(data.progress);
      if (data.log && data.log !== "__DONE__") setUploadProgress(data.log);

      if (data.log === "__DONE__") {
        es.close(); esRef.current = null;

        if (data.status === "done") {
          setUploadPct(100);
          setUploadProgress("Complete! Loading results…");
          await new Promise(res => setTimeout(res, 700));
          setUploadProgress(null); setUploadPct(0);
          // ✅ Auto-loads results the moment pipeline finishes
          await loadJob(jobId);
        } else {
          setUploadProgress(null);
          setAppError("Pipeline error — check backend logs.");
        }
      }
    };

    es.onerror = () => {
      es.close(); esRef.current = null;
      setUploadProgress(null);
      setAppError("Lost connection to backend. Is the server running?");
    };
  }

  // ── Load job results + create/restore chat session ────────────────────
  async function loadJob(jobId) {
    try {
      const r = await fetch(`${API}/api/results/${jobId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) { setAppError("Could not load results."); return; }
      const d = await r.json();

      setActiveJob(d);
      const paperSections = d.document?.sections || [];
      setSections(paperSections);
      setReasoning(d.reasoning?.final_report || d.reasoning?.summary || "");
      setAuditData(d.audit || null);
      setExpanded({});
      setMainTab("sections");

      // ✅ FIX 2: Provide required `name` field when creating a session
      const paperName = d.output_metadata?.filename || "Untitled Paper";
      try {
        const sr = await fetch(`${API}/api/sessions`, {
          method: "POST",
          headers: {
            Authorization:  `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            job_id:   jobId,
            name:     paperName,   // ← was missing before → caused 422 error
            filename: paperName,
          }),
        });
        if (sr.ok) {
          const sd          = await sr.json();
          const newSessionId = sd.session_id || sd.id;
          setSessionId(newSessionId);
          await loadSessionMessages(newSessionId, paperName, paperSections);
        } else {
          setSessionId(null);
          setChatMessages([]);
        }
      } catch {
        setSessionId(null);
        setChatMessages([]);
      }
    } catch (e) {
      setAppError("Load error: " + e.message);
    }
  }

  // ── Load existing messages (restores conversation after page reload) ───
  async function loadSessionMessages(sid, paperName, paperSections) {
    try {
      const r = await fetch(`${API}/api/sessions/${sid}/messages`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const msgs = await r.json();
        if (msgs.length > 0) {
          setChatMessages(msgs.map(m => ({ role: m.role, content: m.content })));
          return;
        }
      }
    } catch {}
    // Default greeting on first load
    setChatMessages([{
      role: "assistant",
      content: `Paper loaded! I've analyzed **${paperName}** — ${paperSections.length} sections extracted.\n\nAsk me anything about this paper — methodology, results, findings, or any specific section.`,
    }]);
  }

  // ── ✅ FIX 1: sendChat — correct URL + correct request body ───────────
  async function sendChat() {
    if (!chatInput.trim() || !sessionId || streaming) return;

    const msg = chatInput.trim();
    setChatInput("");
    setChatMessages(p => [...p, { role: "user", content: msg }]);
    setStreaming(true);
    // Add empty assistant placeholder for streaming animation
    setChatMessages(p => [...p, { role: "assistant", content: "" }]);

    let buffer = "";
    try {
      // ✅ FIX 1a: Correct route   → /api/chat  (not /api/chat/${sessionId}/stream)
      // ✅ FIX 1b: Correct body    → { message, session_id }  (matches ChatRequest in main.py)
      const r = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: {
          Authorization:  `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message:    msg,
          session_id: sessionId,
        }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
        throw new Error(err.detail || `HTTP ${r.status}`);
      }

      const reader = r.body.getReader();
      const dec    = new TextDecoder();

      // Stream tokens from SSE response
      outer: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = dec.decode(value, { stream: true });
        for (const line of text.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const j = JSON.parse(line.slice(6));
            if (j.token === "__DONE__") break outer;
            buffer += j.token;
            setChatMessages(p => {
              const copy = [...p];
              copy[copy.length - 1] = { role: "assistant", content: buffer };
              return copy;
            });
          } catch {}
        }
      }
    } catch (e) {
      setChatMessages(p => {
        const copy = [...p];
        copy[copy.length - 1] = {
          role:    "assistant",
          content: `⚠️ Error: ${e.message}.\n\nMake sure Ollama is running with: ollama serve`,
        };
        return copy;
      });
    } finally {
      setStreaming(false);
    }
  }

  // ── Filtered sections for search ──────────────────────────────────────
  const filteredSections = sections.filter(s =>
    !search ||
    s.title?.toLowerCase().includes(search.toLowerCase()) ||
    s.text?.toLowerCase().includes(search.toLowerCase())
  );

  const card = {
    background: t.bg2,
    border: `1px solid ${t.border}`,
    borderRadius: 14,
    padding: "20px",
  };

  // ══════════════════════════════════════════════════════════════════════
  // AUTH SCREEN
  // ══════════════════════════════════════════════════════════════════════
  if (view === "login") {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center",
        justifyContent: "center", background: t.bg,
        backgroundImage: `
          radial-gradient(ellipse at 20% 50%, ${t.accent}18 0%, transparent 60%),
          radial-gradient(ellipse at 80% 20%, ${t.accent}10 0%, transparent 50%)`,
      }}>
        <button onClick={() => setTheme(p => p === "dark" ? "light" : "dark")}
          style={{ position: "fixed", top: 20, right: 20, ...iconBtn(t) }}>
          {theme === "dark" ? "☀️" : "🌙"}
        </button>

        <div style={{
          width: 400, background: t.bg1, borderRadius: 20,
          padding: "40px 36px", boxShadow: t.shadowLg,
          border: `1px solid ${t.border2}`, animation: "fadeUp 0.4s ease",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 32 }}>
            <Logo size={36} t={t} />
            <div>
              <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 20, color: t.text0, letterSpacing: "-0.5px" }}>
                ResearchAI
              </div>
              <div style={{ fontSize: 11, color: t.text2, letterSpacing: "0.08em", textTransform: "uppercase" }}>
                Paper Intelligence
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 4, marginBottom: 28, background: t.bg3, borderRadius: 10, padding: 4 }}>
            {["login", "register"].map(tab => (
              <button key={tab} onClick={() => { setAuthTab(tab); setAuthError(""); }}
                style={{
                  flex: 1, padding: "8px 0", borderRadius: 8, border: "none",
                  cursor: "pointer", fontFamily: "inherit", fontSize: 13,
                  fontWeight: 600, transition: "all 0.2s",
                  background: authTab === tab ? t.bg1 : "transparent",
                  color:      authTab === tab ? t.text0 : t.text2,
                  boxShadow:  authTab === tab ? t.shadow : "none",
                }}>
                {tab === "login" ? "Sign In" : "Create Account"}
              </button>
            ))}
          </div>

          {authError && (
            <div style={{
              background: `${t.red}18`, border: `1px solid ${t.red}44`,
              borderRadius: 10, padding: "10px 14px", color: t.red,
              fontSize: 13, marginBottom: 16, animation: "fadeUp 0.2s ease",
            }}>
              {authError}
            </div>
          )}

          {authTab === "login" ? (
            <>
              <AuthInput label="Username" value={loginForm.username} t={t}
                onChange={v => setLoginForm(p => ({...p, username: v}))} onEnter={handleAuth} />
              <AuthInput label="Password" type="password" value={loginForm.password} t={t}
                onChange={v => setLoginForm(p => ({...p, password: v}))} onEnter={handleAuth} />
            </>
          ) : (
            <>
              <AuthInput label="Username (min 3 chars)" value={regForm.username} t={t}
                onChange={v => setRegForm(p => ({...p, username: v}))} onEnter={handleAuth} />
              <AuthInput label="Password (min 6 chars)" type="password" value={regForm.password} t={t}
                onChange={v => setRegForm(p => ({...p, password: v}))} onEnter={handleAuth} />
            </>
          )}

          <button onClick={handleAuth} disabled={authLoading}
            style={{
              width: "100%", padding: "12px 0", marginTop: 8,
              background: authLoading ? t.bg4 : t.accent,
              color: "#fff", border: "none", borderRadius: 10,
              fontFamily: "inherit", fontSize: 14, fontWeight: 600,
              cursor: authLoading ? "not-allowed" : "pointer",
              transition: "all 0.2s", display: "flex",
              alignItems: "center", justifyContent: "center", gap: 8,
            }}>
            {authLoading
              ? <><Spinner t={t} /> Processing…</>
              : authTab === "login" ? "Sign In →" : "Create Account →"}
          </button>
        </div>
      </div>
    );
  }

  // ══════════════════════════════════════════════════════════════════════
  // MAIN APP
  // ══════════════════════════════════════════════════════════════════════
  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100vh",
      background: t.bg, color: t.text0,
      fontFamily: "'Instrument Sans', sans-serif", overflow: "hidden",
    }}>

      {/* ── Topbar ── */}
      <header style={{
        height: 52, display: "flex", alignItems: "center", padding: "0 16px",
        borderBottom: `1px solid ${t.border}`, background: t.bg1,
        gap: 12, flexShrink: 0, zIndex: 100,
      }}>
        <button onClick={() => setSidebarOpen(p => !p)} style={iconBtn(t)}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4h12M2 8h12M2 12h12" stroke={t.text2} strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <Logo size={24} t={t} />
          <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 16, color: t.text0, letterSpacing: "-0.3px" }}>
            ResearchAI
          </span>
        </div>

        {activeJob && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: t.bg3, borderRadius: 8, padding: "4px 12px",
            border: `1px solid ${t.border2}`, maxWidth: 280,
          }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2 1h6l2 2v8H2V1z" stroke={t.accent} strokeWidth="1.2"/>
              <path d="M8 1v2h2" stroke={t.accent} strokeWidth="1.2"/>
            </svg>
            <span style={{ fontSize: 12, color: t.text1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {activeJob.output_metadata?.filename || "Paper loaded"}
            </span>
          </div>
        )}

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: t.text2 }}>{username}</span>
          <button onClick={() => setTheme(p => p === "dark" ? "light" : "dark")} style={iconBtn(t)}>
            {theme === "dark" ? (
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <circle cx="7.5" cy="7.5" r="3" stroke={t.text2} strokeWidth="1.3"/>
                <path d="M7.5 1v1.5M7.5 12.5V14M1 7.5h1.5M12.5 7.5H14M3.22 3.22l1.06 1.06M10.72 10.72l1.06 1.06M3.22 11.78l1.06-1.06M10.72 4.28l1.06-1.06" stroke={t.text2} strokeWidth="1.3" strokeLinecap="round"/>
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                <path d="M12.5 8.5A5.5 5.5 0 016.5 2.5a5.5 5.5 0 100 10 5.5 5.5 0 006-4z" stroke={t.text2} strokeWidth="1.3"/>
              </svg>
            )}
          </button>
          <button onClick={logout} style={{ ...iconBtn(t), color: t.red, fontSize: 12, fontFamily: "inherit" }}>
            Sign out
          </button>
          <button onClick={() => setRightOpen(p => !p)} style={iconBtn(t)}>
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <rect x="1" y="1" width="13" height="13" rx="2" stroke={t.text2} strokeWidth="1.3"/>
              <path d="M10 1v13" stroke={t.text2} strokeWidth="1.3"/>
            </svg>
          </button>
        </div>
      </header>

      {/* ── Body ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── Sidebar ── */}
        {sidebarOpen && (
          <aside style={{
            width: 260, borderRight: `1px solid ${t.border}`,
            background: t.bg1, display: "flex", flexDirection: "column",
            flexShrink: 0, overflow: "hidden", animation: "slideIn 0.2s ease",
          }}>
            {/* Upload zone */}
            <div style={{ padding: "14px 14px 10px" }}>
              <div
                onClick={() => !uploadProgress && fileInputRef.current?.click()}
                onDragOver={e => e.preventDefault()}
                onDrop={e => { e.preventDefault(); handleUpload(e.dataTransfer.files[0]); }}
                style={{
                  border: `1.5px dashed ${uploadProgress ? t.accent : t.border3}`,
                  borderRadius: 12, padding: "16px 12px", textAlign: "center",
                  cursor: uploadProgress ? "not-allowed" : "pointer",
                  background: uploadProgress ? t.accentBg : "transparent",
                  transition: "all 0.2s",
                }}>
                {uploadProgress ? (
                  <>
                    <div style={{ fontSize: 12, color: t.accent, marginBottom: 6, fontWeight: 600 }}>
                      {uploadProgress}
                    </div>
                    <div style={{ height: 4, background: t.bg4, borderRadius: 2, overflow: "hidden" }}>
                      <div style={{
                        height: "100%", width: `${uploadPct}%`,
                        background: `linear-gradient(90deg, ${t.accent}, ${t.accentHov})`,
                        borderRadius: 2, transition: "width 0.8s ease",
                      }} />
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 22, marginBottom: 6 }}>📄</div>
                    <div style={{ fontSize: 12, color: t.text1, fontWeight: 500 }}>Upload PDF</div>
                    <div style={{ fontSize: 11, color: t.text3, marginTop: 2 }}>click or drag & drop</div>
                  </>
                )}
                <input ref={fileInputRef} type="file" accept=".pdf"
                  style={{ display: "none" }}
                  onChange={e => handleUpload(e.target.files[0])} />
              </div>
            </div>

            {/* Active paper info */}
            {activeJob && (
              <div style={{ padding: "0 14px 10px" }}>
                <div style={{
                  background: t.accentBg, border: `1px solid ${t.accent}30`,
                  borderRadius: 10, padding: "10px 12px",
                }}>
                  <div style={{ fontSize: 11, color: t.accent, fontWeight: 600, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Active Paper
                  </div>
                  <div style={{ fontSize: 12, color: t.text0, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {activeJob.output_metadata?.filename}
                  </div>
                  <div style={{ fontSize: 11, color: t.text2, marginTop: 3 }}>
                    {activeJob.output_metadata?.total_pages} pages · {sections.length} sections
                  </div>
                </div>
              </div>
            )}

            <div style={{ flex: 1 }} />

            {/* Navigation */}
            <div style={{ padding: "10px 14px", borderTop: `1px solid ${t.border}` }}>
              <div style={{ fontSize: 11, color: t.text3, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Navigation
              </div>
              {[
                { id: "sections", icon: "≡", label: "Sections" },
                { id: "chat",     icon: "💬", label: "Chat with Paper" },
              ].map(nav => (
                <button key={nav.id} onClick={() => setMainTab(nav.id)}
                  disabled={!activeJob}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%",
                    padding: "8px 10px", borderRadius: 8, border: "none",
                    cursor: activeJob ? "pointer" : "not-allowed",
                    background: mainTab === nav.id && activeJob ? t.accentBg : "transparent",
                    color: mainTab === nav.id && activeJob ? t.accent : activeJob ? t.text1 : t.text3,
                    fontFamily: "inherit", fontSize: 13, fontWeight: mainTab === nav.id ? 600 : 400,
                    marginBottom: 2, transition: "all 0.15s", textAlign: "left",
                  }}>
                  <span style={{ fontSize: 14 }}>{nav.icon}</span>
                  {nav.label}
                </button>
              ))}
            </div>
          </aside>
        )}

        {/* ── Main content ── */}
        <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
          {appError && (
            <div style={{
              margin: 16, padding: "10px 16px", borderRadius: 10,
              background: `${t.red}18`, border: `1px solid ${t.red}40`,
              color: t.red, fontSize: 13,
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              {appError}
              <button onClick={() => setAppError("")}
                style={{ background: "none", border: "none", color: t.red, cursor: "pointer", fontSize: 16 }}>
                ×
              </button>
            </div>
          )}

          {!activeJob ? (
            // ── Empty state ──
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 20, padding: 40 }}>
              <div style={{ width: 80, height: 80, borderRadius: 20, background: t.accentBg, border: `1px solid ${t.accent}30`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Logo size={40} t={t} />
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 22, fontWeight: 700, color: t.text0, marginBottom: 8 }}>
                  Welcome to ResearchAI
                </div>
                <div style={{ fontSize: 14, color: t.text2, maxWidth: 400, lineHeight: 1.7 }}>
                  Upload a research paper PDF to extract sections, run AI analysis,
                  and chat with the content using DeepSeek.
                </div>
              </div>
              <button onClick={() => fileInputRef.current?.click()}
                style={{ padding: "12px 28px", background: t.accent, color: "#fff", border: "none", borderRadius: 10, fontFamily: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
                Upload Paper →
              </button>
            </div>

          ) : mainTab === "sections" ? (
            // ── SECTIONS TAB ──
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
              <div style={{ marginBottom: 20, position: "relative", maxWidth: 560 }}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                  style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)" }}>
                  <circle cx="6" cy="6" r="4.5" stroke={t.text3} strokeWidth="1.3"/>
                  <path d="M10 10l2.5 2.5" stroke={t.text3} strokeWidth="1.3" strokeLinecap="round"/>
                </svg>
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="Search sections…"
                  style={{
                    width: "100%", padding: "10px 14px 10px 34px",
                    background: t.bg2, border: `1px solid ${t.border2}`,
                    borderRadius: 10, color: t.text0, fontSize: 13,
                    fontFamily: "inherit", outline: "none",
                  }} />
              </div>

              <div style={{ fontSize: 12, color: t.text3, marginBottom: 14, fontWeight: 500 }}>
                {filteredSections.length} section{filteredSections.length !== 1 ? "s" : ""}
                {search && ` matching "${search}"`}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {filteredSections.map((s, i) => (
                  <div key={i} style={{
                    background: t.bg2,
                    border: `1px solid ${expanded[i] ? t.border2 : t.border}`,
                    borderRadius: 12, overflow: "hidden",
                    transition: "border-color 0.2s",
                    animation: `fadeUp 0.3s ease ${i * 0.03}s both`,
                  }}>
                    <button onClick={() => setExpanded(p => ({...p, [i]: !p[i]}))}
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "13px 16px", width: "100%", background: "none", border: "none", cursor: "pointer", textAlign: "left" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 10, color: t.accent, background: t.accentBg, padding: "2px 7px", borderRadius: 99, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>
                          p.{s.page_start}
                        </span>
                        <span style={{ fontSize: 13, color: t.text0, fontWeight: 600 }}>{s.title}</span>
                      </div>
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                        style={{ transform: expanded[i] ? "rotate(180deg)" : "none", transition: "transform 0.2s", flexShrink: 0 }}>
                        <path d="M3 5l4 4 4-4" stroke={t.text3} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </button>
                    {expanded[i] && (
                      <div style={{ padding: "0 16px 16px", borderTop: `1px solid ${t.border}`, color: t.text1, fontSize: 13, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                        <div style={{ height: 12 }} />
                        {s.text || <span style={{ color: t.text3, fontStyle: "italic" }}>No text extracted for this section.</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

          ) : (
            // ── CHAT TAB ──
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              {/* Warning if session failed to create */}
              {!sessionId && (
                <div style={{
                  margin: "12px 24px 0", padding: "8px 14px", borderRadius: 8,
                  background: `${t.yellow}18`, border: `1px solid ${t.yellow}40`,
                  color: t.yellow, fontSize: 12,
                }}>
                  ⚠️ Chat session not initialised. Try re-uploading the paper.
                </div>
              )}

              {/* Messages */}
              <div style={{ flex: 1, overflowY: "auto", padding: "24px", display: "flex", flexDirection: "column", gap: 16 }}>
                {chatMessages.map((m, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", animation: "fadeUp 0.25s ease" }}>
                    {m.role === "assistant" && (
                      <div style={{ width: 28, height: 28, borderRadius: 8, background: t.accentBg, display: "flex", alignItems: "center", justifyContent: "center", marginRight: 10, flexShrink: 0, marginTop: 2 }}>
                        <Logo size={16} t={t} />
                      </div>
                    )}
                    <div style={{
                      maxWidth: "72%", padding: "12px 16px",
                      borderRadius: m.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
                      background: m.role === "user" ? t.accent : t.bg3,
                      color:      m.role === "user" ? "#fff" : t.text0,
                      fontSize: 14, lineHeight: 1.75, whiteSpace: "pre-wrap",
                      border: m.role === "assistant" ? `1px solid ${t.border}` : "none",
                    }}>
                      {m.content || <span style={{ animation: "shimmer 1s infinite", opacity: 0.5 }}>●●●</span>}
                    </div>
                  </div>
                ))}

                {/* Typing indicator */}
                {streaming && chatMessages[chatMessages.length - 1]?.content === "" && (
                  <div style={{ display: "flex", gap: 4, paddingLeft: 38 }}>
                    {[0, 1, 2].map(i => (
                      <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: t.text3, animation: `shimmer 1.2s infinite ${i * 0.2}s` }} />
                    ))}
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Input */}
              <div style={{ padding: "16px 24px", borderTop: `1px solid ${t.border}`, background: t.bg1, display: "flex", gap: 10, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}>
                  <textarea
                    value={chatInput}
                    onChange={e => {
                      setChatInput(e.target.value);
                      e.target.style.height = "auto";
                      e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
                    }}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
                    placeholder={sessionId ? "Ask anything about this paper… (Enter to send, Shift+Enter for newline)" : "Upload a paper first to start chatting"}
                    disabled={!sessionId}
                    rows={1}
                    style={{
                      width: "100%", padding: "11px 14px",
                      background: t.bg2, border: `1px solid ${t.border2}`,
                      borderRadius: 12, color: t.text0, fontSize: 14,
                      fontFamily: "inherit", outline: "none", resize: "none",
                      lineHeight: 1.5, maxHeight: 120, overflow: "auto",
                      transition: "border-color 0.2s", opacity: sessionId ? 1 : 0.5,
                    }}
                    onFocus={e => e.target.style.borderColor = t.accent}
                    onBlur={e  => e.target.style.borderColor = t.border2}
                  />
                </div>
                <button onClick={sendChat}
                  disabled={streaming || !chatInput.trim() || !sessionId}
                  style={{
                    width: 42, height: 42, borderRadius: 10, border: "none",
                    background: (streaming || !chatInput.trim() || !sessionId) ? t.bg4 : t.accent,
                    cursor: (streaming || !chatInput.trim() || !sessionId) ? "not-allowed" : "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    transition: "all 0.2s", flexShrink: 0,
                  }}>
                  {streaming ? <Spinner t={t} /> : (
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <path d="M2 8h12M9 3l5 5-5 5" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                </button>
              </div>
            </div>
          )}
        </main>

        {/* ── Right panel ── */}
        {rightOpen && activeJob && (
          <aside style={{ width: 300, borderLeft: `1px solid ${t.border}`, background: t.bg1, overflowY: "auto", flexShrink: 0, padding: "20px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
            {auditData && (
              <div style={{ ...card, background: t.bg2 }}>
                <div style={{ fontSize: 10, color: t.text3, textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 14 }}>Audit Score</div>
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <ScoreRing score={auditData.score || 0} t={t} />
                  <div>
                    <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "'Syne', sans-serif", color: (auditData.score||0) >= 75 ? t.green : (auditData.score||0) >= 50 ? t.yellow : t.red }}>
                      {auditData.grade}
                    </div>
                    <div style={{ fontSize: 11, color: t.text2 }}>{auditData.status}</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
                  {Object.entries(auditData.counts || {}).map(([k, v]) => (
                    <span key={k} style={{ fontSize: 10, padding: "3px 8px", borderRadius: 99, fontWeight: 600, background: k === "CRITICAL" ? `${t.red}18` : k === "PASS" ? `${t.green}18` : t.bg4, color: k === "CRITICAL" ? t.red : k === "PASS" ? t.green : t.text2 }}>
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ ...card, background: t.bg2 }}>
              <div style={{ fontSize: 10, color: t.text3, textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 12 }}>Paper Stats</div>
              {[
                ["Pages",    activeJob.output_metadata?.total_pages],
                ["Sections", sections.length],
                ["Tables",   activeJob.document?.tables?.length],
                ["Figures",  activeJob.document?.figures?.length],
              ].map(([label, val]) => val !== undefined && (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <span style={{ fontSize: 12, color: t.text2 }}>{label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: t.text0 }}>{val ?? "—"}</span>
                </div>
              ))}
            </div>

            {reasoning && (
              <div style={{ ...card, background: t.bg2 }}>
                <div style={{ fontSize: 10, color: t.text3, textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700, marginBottom: 12 }}>AI Summary</div>
                <div style={{ fontSize: 12, color: t.text1, lineHeight: 1.8, whiteSpace: "pre-wrap", maxHeight: 400, overflowY: "auto" }}>
                  {reasoning}
                </div>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

// ── Helper components ─────────────────────────────────────────────────────
function AuthInput({ label, type = "text", value, onChange, onEnter, t }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ fontSize: 12, color: t.text2, fontWeight: 500, display: "block", marginBottom: 6 }}>
        {label}
      </label>
      <input
        type={type} value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => e.key === "Enter" && onEnter?.()}
        style={{
          display: "block", width: "100%", padding: "10px 14px",
          background: t.bg3, border: `1px solid ${t.border2}`,
          borderRadius: 10, color: t.text0, fontSize: 14,
          fontFamily: "inherit", outline: "none", transition: "border-color 0.2s",
        }}
        onFocus={e => e.target.style.borderColor = t.accent}
        onBlur={e  => e.target.style.borderColor = t.border2}
      />
    </div>
  );
}

function iconBtn(t) {
  return {
    background: "none", border: "1px solid transparent", borderRadius: 8,
    cursor: "pointer", color: t.text2, padding: "6px 8px",
    display: "flex", alignItems: "center", justifyContent: "center",
    transition: "all 0.15s", fontFamily: "inherit",
  };
}