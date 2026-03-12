const params = new URLSearchParams(location.search);
const SERVER = params.get("server")
  || (typeof window.MCP_SERVER_URL !== "undefined" ? window.MCP_SERVER_URL : null)
  || "http://127.0.0.1:8000";

const ci     = document.getElementById("ci");
const chatEl = document.getElementById("chat");
const qEl    = document.getElementById("q");
const sbtn   = document.getElementById("sbtn");
const dLog   = document.getElementById("dbg-log");
let dbgOpen  = false;

// ── Debug panel ───────────────────────────────────────────
function toggleDbg() {
  dbgOpen = !dbgOpen;
  document.getElementById("dbg").classList.toggle("open", dbgOpen);
  document.getElementById("chat-wrap").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("ibar").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("dbgbtn").classList.toggle("active", dbgOpen);
  document.getElementById("te").classList.toggle("active", dbgOpen);
  document.getElementById("tc").classList.toggle("active", !dbgOpen);
}

// ── Health ────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch(`${SERVER}/health`);
    if (!r.ok) throw new Error();
    const d = await r.json();
    document.getElementById("abadge").className = "badge on";
    document.getElementById("abadge").textContent = "ONLINE";
    document.getElementById("amodel").textContent = `${d.model} · ${d.tools.length} tools`;
    dlog("info", `Connected · ${d.model}`);
    dlog("info", `Tools: ${d.tools.join(", ")}`);
  } catch {
    document.getElementById("abadge").className = "badge off";
    document.getElementById("abadge").textContent = "OFFLINE";
    document.getElementById("amodel").textContent = SERVER;
    dlog("error", `Cannot reach ${SERVER}`);
  }
}

// ── Helpers ───────────────────────────────────────────────
function ts()  { return new Date().toLocaleTimeString("en-GB", {hour12:false}); }
function tstr(){ return new Date().toLocaleTimeString("en-US",{hour:"numeric",minute:"2-digit"}); }
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function sc()  { chatEl.scrollTop = chatEl.scrollHeight; }
function uid() { return "_" + Math.random().toString(36).slice(2,9); }

function dlog(type, txt) {
  const el = document.createElement("div");
  el.className = `de ${type}`;
  el.innerHTML = `<div class="de-ts">${ts()}</div><div class="de-body">${esc(txt)}</div>`;
  dLog.appendChild(el);
  dLog.scrollTop = dLog.scrollHeight;
}

// ── SVG icons ─────────────────────────────────────────────
const STAR_SVG = `<svg viewBox="0 0 24 24" fill="none">
  <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"
    stroke="#00FF00" stroke-width="2" stroke-linecap="round"/></svg>`;
const DONE_SVG = `<svg viewBox="0 0 24 24" fill="none">
  <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"
    stroke="#00FF00" stroke-width="2" stroke-linecap="round" opacity=".2"/>
  <circle cx="12" cy="12" r="4.5" fill="#00FF00"/></svg>`;
const TOOL_ICO = {
  internet_search:  `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 3c-2 2-2 12 0 14M10 3c2 2 2 12 0 14M3 10h14" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  get_weather:      `<svg viewBox="0 0 20 20" fill="none"><path d="M4 13a4 4 0 110-8 5.5 5.5 0 019 1.5A3 3 0 1116 13H4z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  get_current_time: `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  read_doc_content: `<svg viewBox="0 0 20 20" fill="none"><rect x="4" y="2" width="12" height="16" rx="2" stroke="#8e8e93" stroke-width="1.5"/><path d="M7 7h6M7 10h6M7 13h4" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  edit_doc_content: `<svg viewBox="0 0 20 20" fill="none"><path d="M4 16l3-1 9-9-2-2-9 9-1 3z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  _default:         `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="6" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 7v3l2 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};

// ══════════════════════════════════════════════════════════
//  TURN — all state is scoped to one object per request
// ══════════════════════════════════════════════════════════
class Turn {
  constructor() {
    this.id         = uid();          // unique per turn
    this.thinkEl    = null;           // the .think-wrap DOM node
    this.stepsEl    = null;           // .tk-steps inside it
    this.bubbleEl   = null;           // the .bubble DOM node for answer
    this.tsEl       = null;           // .msg-ts
    this.collapsed  = false;
    this.toolsUsed  = [];
    this.hasThink   = false;
  }

  // ── Create the dark thinking card ──────────────────────
  initThink() {
    if (this.hasThink) return;
    this.hasThink = true;

    const sid = this.id + "_s";   // steps id
    const hid = this.id + "_h";   // header id
    const iid = this.id + "_i";   // icon id
    const tid = this.id + "_t";   // title id

    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.innerHTML = `
      <div class="msg-row">
        <div class="bot-av">⚙</div>
        <div class="think-wrap">
          <div class="tk-hdr" id="${hid}" onclick="turns['${this.id}'].toggle()">
            <div class="tk-star" id="${iid}">${STAR_SVG}</div>
            <span class="tk-title" id="${tid}">Working</span>
            <span class="tk-chev">▼</span>
          </div>
          <div class="tk-steps" id="${sid}"></div>
        </div>
      </div>`;
    ci.appendChild(wrap);

    this.stepsEl = document.getElementById(sid);
    this.thinkEl = document.getElementById(hid)?.closest(".think-wrap");
    sc();
  }

  toggle() {
    this.collapsed = !this.collapsed;
    const sid = this.id + "_s";
    const hid = this.id + "_h";
    document.getElementById(sid)?.classList.toggle("collapsed", this.collapsed);
    document.getElementById(hid)?.classList.toggle("collapsed", this.collapsed);
  }

  setTitle(t) {
    const el = document.getElementById(this.id + "_t");
    if (el) el.textContent = t;
  }

  addStep(toolName, label, tag) {
    if (!this.stepsEl) return;
    const icon = TOOL_ICO[toolName] || TOOL_ICO._default;
    const el = document.createElement("div");
    el.className = "tk-step";
    el.innerHTML = `
      <div class="tk-ico">${icon}</div>
      <div class="tk-info">
        <span class="tk-lbl">${esc(label)}</span>
        ${tag ? `<span class="tk-tag">${esc(tag)}</span>` : ""}
      </div>`;
    this.stepsEl.appendChild(el);
    this.stepsEl.scrollTop = this.stepsEl.scrollHeight;
    sc();
  }

  addSearching(query) {
    if (!this.stepsEl) return;
    const el = document.createElement("div");
    el.className = "tk-step";
    el.innerHTML = `
      <div class="tk-ico">${TOOL_ICO.internet_search}</div>
      <div class="tk-info" style="flex:1">
        <span class="tk-lbl">Searching the web</span>
        <span class="tk-tag">${esc(query.slice(0,55))}</span>
      </div>
      <div class="tk-dots"><span></span><span></span><span></span></div>`;
    this.stepsEl.appendChild(el);
    this.stepsEl.scrollTop = this.stepsEl.scrollHeight;
    sc();
  }

  addDone() {
    if (!this.stepsEl) return;
    const el = document.createElement("div");
    el.className = "tk-step";
    el.innerHTML = `
      <div class="tk-ico">
        <svg viewBox="0 0 20 20" fill="none">
          <path d="M4 10l4 4 8-8" stroke="#00FF00" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <div class="tk-info"><span class="tk-lbl" style="color:#00cc00">Got response</span></div>`;
    this.stepsEl.appendChild(el);
    this.stepsEl.scrollTop = this.stepsEl.scrollHeight;
    sc();
  }

  finish() {
    const ico = document.getElementById(this.id + "_i");
    const ttl = document.getElementById(this.id + "_t");
    if (ico) { ico.innerHTML = DONE_SVG; ico.classList.add("done"); }
    if (ttl) ttl.textContent = this.toolsUsed.length
      ? `Used ${this.toolsUsed.join(", ")}` : "Done";
    setTimeout(() => { if (!this.collapsed) this.toggle(); }, 700);
  }

  // ── Answer bubble (separate from thinking) ─────────────
  initBubble() {
    const bid = this.id + "_b";
    const tsid = this.id + "_ts";
    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.innerHTML = `
      <div class="msg-row">
        <div class="bot-av">⚙</div>
        <div class="bubble" id="${bid}"><span class="cur"></span></div>
      </div>
      <div class="msg-ts" id="${tsid}"></div>`;
    ci.appendChild(wrap);
    this.bubbleEl = document.getElementById(bid);
    this.tsEl     = document.getElementById(tsid);
    sc();
  }

  stream(text) {
    if (this.bubbleEl)
      this.bubbleEl.innerHTML = esc(text) + '<span class="cur"></span>';
    sc();
  }

  finalize(text) {
    if (this.bubbleEl) { this.bubbleEl.textContent = text; }
    if (this.tsEl)     { this.tsEl.textContent = tstr(); }
    sc();
  }
}

// Global turn registry so onclick handlers can find their turn
const turns = {};

// ── User bubble ───────────────────────────────────────────
function addUser(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="msg-row"><div class="bubble">${esc(text)}</div></div>
                  <div class="msg-ts">${tstr()}</div>`;
  ci.appendChild(el);
  sc();
}

async function streamWords(turn, text) {
  turn.initBubble();
  const words = text.split(" ");
  let built = "";
  for (let i = 0; i < words.length; i++) {
    built += (i > 0 ? " " : "") + words[i];
    turn.stream(built);
    if (i % 5 === 4) await wait(12);
  }
  turn.finalize(text);
}
function wait(ms){ return new Promise(r => setTimeout(r, ms)); }

// ── Send ──────────────────────────────────────────────────
async function send() {
  const query = qEl.value.trim();
  if (!query) return;
  qEl.value = "";
  qEl.style.height = "24px";
  sbtn.disabled = true;

  addUser(query);
  dlog("info", `→ ${query}`);

  // Create a fresh Turn object for this request
  const turn = new Turn();
  turns[turn.id] = turn;

  let answer = "";

  try {
    const resp = await fetch(`${SERVER}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") break;
        try {
          const evt = JSON.parse(raw);

          switch (evt.type) {

            case "debug":
              dlog("info", evt.text);
              // Show thinking block only if tools will be used (not pure conversation)
              if (!turn.hasThink && !evt.text.toLowerCase().includes("conversation")) {
                turn.initThink();
              }
              break;

            case "tool_call": {
              // Always show thinking block for tool calls
              if (!turn.hasThink) turn.initThink();
              turn.toolsUsed.push(evt.name);
              dlog("tool", `→ ${evt.name}(${JSON.stringify(evt.args)})`);

              if (evt.name === "internet_search") {
                const q = (evt.args?.query) || query;
                turn.addSearching(q);
                turn.setTitle("Searching the web…");
              } else {
                const labels = {
                  get_weather:      "Checking weather",
                  get_current_time: "Getting current time",
                  read_doc_content: "Reading document",
                  edit_doc_content: "Editing document",
                };
                const tag = Object.values(evt.args || {}).join(", ").slice(0, 55) || null;
                turn.addStep(evt.name, labels[evt.name] || evt.name, tag);
                turn.setTitle(`Using ${evt.name}…`);
              }
              break;
            }

            case "tool_result":
              dlog("result", `← ${evt.name}: ${evt.result.slice(0, 80)}`);
              if (turn.hasThink) turn.addDone();
              break;

            case "answer":
              answer = evt.text;
              dlog("answer", `Answer (${answer.length} chars)`);
              if (turn.hasThink) {
                turn.finish();
                await wait(750);
              }
              await streamWords(turn, answer);
              break;

            case "error":
              dlog("error", evt.text);
              if (turn.hasThink) turn.finish();
              turn.initBubble();
              turn.finalize(`⚠ ${evt.text}`);
              break;
          }
        } catch(_) {}
      }
    }

    if (!answer) {
      if (turn.hasThink) turn.finish();
      turn.initBubble();
      turn.finalize("(no response)");
    }

  } catch(e) {
    if (turn.hasThink) turn.finish();
    turn.initBubble();
    turn.finalize(`⚠ ${e.message}`);
    dlog("error", e.message);
    document.getElementById("abadge").className = "badge off";
    document.getElementById("abadge").textContent = "OFFLINE";
  } finally {
    // Clean up registry after a delay (keep for toggle onclick)
    setTimeout(() => { delete turns[turn.id]; }, 30000);
    sbtn.disabled = false;
    qEl.focus();
  }
}

// ── Textarea ──────────────────────────────────────────────
qEl.addEventListener("input", () => {
  qEl.style.height = "24px";
  qEl.style.height = Math.min(qEl.scrollHeight, 130) + "px";
});
qEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
function fill(t){ qEl.value=t; qEl.focus(); qEl.dispatchEvent(new Event("input")); }

checkHealth();
