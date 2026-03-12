// ── Config ────────────────────────────────────────────────────────────────────
const SERVER = (new URLSearchParams(location.search).get("server"))
  || (typeof window.MCP_SERVER_URL !== "undefined" ? window.MCP_SERVER_URL : null)
  || `${location.protocol}//${location.hostname}:8000`;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const ci     = document.getElementById("ci");
const chatEl = document.getElementById("chat");
const qEl    = document.getElementById("q");
const sbtn   = document.getElementById("sbtn");
const dLog   = document.getElementById("dbg-log");
let dbgOpen  = false;

// ── Debug panel ───────────────────────────────────────────────────────────────
function toggleDbg() {
  dbgOpen = !dbgOpen;
  document.getElementById("dbg").classList.toggle("open", dbgOpen);
  document.getElementById("chat-wrap").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("ibar").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("dbgbtn").classList.toggle("active", dbgOpen);
  document.getElementById("te").classList.toggle("active", dbgOpen);
  document.getElementById("tc").classList.toggle("active", !dbgOpen);
}

// ── Health check ──────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch(`${SERVER}/health`);
    if (!r.ok) throw new Error();
    const d = await r.json();
    document.getElementById("abadge").className = "badge on";
    document.getElementById("abadge").textContent = "ONLINE";
    document.getElementById("amodel").textContent = `${d.model} · ${d.tools.length} tools`;
    dlog("info", `Connected — ${d.model}`);
    dlog("info", `Tools: ${d.tools.join(", ")}`);
  } catch {
    document.getElementById("abadge").className = "badge off";
    document.getElementById("abadge").textContent = "OFFLINE";
    document.getElementById("amodel").textContent = SERVER;
    dlog("error", `Cannot reach ${SERVER}`);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const ts   = () => new Date().toLocaleTimeString("en-GB", { hour12: false });
const tstr = () => new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const esc  = s  => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const sc   = () => { chatEl.scrollTop = chatEl.scrollHeight; };
const uid  = () => "_" + Math.random().toString(36).slice(2, 9);
const wait = ms => new Promise(r => setTimeout(r, ms));

function dlog(type, txt) {
  const el = document.createElement("div");
  el.className = "de " + type;
  el.innerHTML = `<div class="de-ts">${ts()}</div><div class="de-body">${esc(txt)}</div>`;
  dLog.appendChild(el);
  dLog.scrollTop = dLog.scrollHeight;
}

// ── Copy code ─────────────────────────────────────────────────────────────────
function copyCode(btn) {
  const pre = btn.closest(".code-block").querySelector("pre");
  navigator.clipboard.writeText(pre.innerText).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  });
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function md(raw) {
  if (!raw) return "";

  // Step 1: extract fenced code blocks BEFORE any escaping
  const blocks = [];
  let text = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push({ lang: (lang || "code").trim(), code: code.trimEnd() });
    return "\x00BLOCK" + (blocks.length - 1) + "\x00";
  });

  // Step 2: escape HTML in the non-code parts
  text = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Step 3: inline formatting
  // bold+italic
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  // bold
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  // italic (only when surrounded by non-space)
  text = text.replace(/\*(\S[^*]*?\S|\S)\*/g, "<em>$1</em>");
  // inline code
  text = text.replace(/`([^`\n]+)`/g,
    '<code class="icode">$1</code>');

  // Step 4: block-level (line by line)
  const lines = text.split("\n");
  const out = [];
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // code block placeholder
    if (/^\x00BLOCK(\d+)\x00$/.test(line)) {
      if (inList) { out.push("</ul>"); inList = false; }
      const idx = parseInt(line.match(/\d+/)[0]);
      const { lang, code } = blocks[idx];
      const escaped = code.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
      out.push(
        `<div class="code-block">` +
        `<div class="code-hdr">` +
        `<span class="code-lang">${esc(lang)}</span>` +
        `<button class="code-copy" onclick="copyCode(this)">Copy</button>` +
        `</div><pre>${escaped}</pre></div>`
      );
      continue;
    }

    // headings
    if (/^### /.test(line)) { out.push(`<h4>${line.slice(4)}</h4>`); continue; }
    if (/^## /.test(line))  { out.push(`<h3>${line.slice(3)}</h3>`); continue; }
    if (/^# /.test(line))   { out.push(`<h2>${line.slice(2)}</h2>`); continue; }

    // bullet list
    const bullet = line.match(/^[ \t]*[-*•] (.+)/);
    if (bullet) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${bullet[1]}</li>`);
      continue;
    }

    // numbered list
    const numbered = line.match(/^(\d+)\. (.+)/);
    if (numbered) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${numbered[1]}. ${numbered[2]}</li>`);
      continue;
    }

    // end list
    if (inList && line.trim() === "") {
      out.push("</ul>");
      inList = false;
      out.push("<br>");
      continue;
    }

    // tool key : value lines (e.g. "  condition  : Haze")
    const kv = line.match(/^([ \t]*)([a-zA-Z][\w\s]{1,25}?)\s*:\s*(.+)$/);
    if (kv && !line.startsWith("http") && !line.includes("://")) {
      out.push(
        `<div class="kv-row">` +
        `<span class="kv-key">${kv[2].trim()}</span>` +
        `<span class="kv-val">${kv[3]}</span></div>`
      );
      continue;
    }

    // blank line → spacing
    if (line.trim() === "") {
      if (out.length && out[out.length-1] !== "<br>") out.push("<br>");
      continue;
    }

    out.push(`<span>${line}</span><br>`);
  }

  if (inList) out.push("</ul>");
  return out.join("\n");
}

// ── SVG icons ─────────────────────────────────────────────────────────────────
const SPIN_SVG = `<svg viewBox="0 0 24 24" fill="none">
  <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"
    stroke="var(--green-mid)" stroke-width="2" stroke-linecap="round"/></svg>`;

const DONE_SVG = `<svg viewBox="0 0 20 20" fill="none">
  <path d="M4 10l4 4 8-8" stroke="var(--green-mid)" stroke-width="1.8"
    stroke-linecap="round" stroke-linejoin="round"/></svg>`;

const TOOL_ICO = {
  internet_search:  `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 3c-2 2-2 12 0 14M10 3c2 2 2 12 0 14M3 10h14" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  get_weather:      `<svg viewBox="0 0 20 20" fill="none"><path d="M4 13a4 4 0 110-8 5.5 5.5 0 019 1.5A3 3 0 1116 13H4z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  get_current_time: `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  read_doc_content: `<svg viewBox="0 0 20 20" fill="none"><rect x="4" y="2" width="12" height="16" rx="2" stroke="#8e8e93" stroke-width="1.5"/><path d="M7 7h6M7 10h6M7 13h4" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  edit_doc_content: `<svg viewBox="0 0 20 20" fill="none"><path d="M4 16l3-1 9-9-2-2-9 9-1 3z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  _default:         `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="6" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 7v3l2 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};

const TOOL_LABELS = {
  get_weather:      "Checking weather",
  get_current_time: "Getting current time",
  read_doc_content: "Reading document",
  edit_doc_content: "Editing document",
  internet_search:  "Searching the web",
};

// ══════════════════════════════════════════════════════════════════════════════
//  Turn — all per-request DOM state
// ══════════════════════════════════════════════════════════════════════════════
class Turn {
  constructor() {
    this.id        = uid();
    this.stepsEl   = null;
    this.bubbleEl  = null;
    this.tsEl      = null;
    this.collapsed = false;
    this.toolsUsed = [];
    this.hasThink  = false;
    this.isDirect  = false;
  }

  initThink() {
    if (this.hasThink) return;
    this.hasThink = true;
    const sid = this.id + "_s";
    const hid = this.id + "_h";
    const tid = this.id + "_t";
    const iid = this.id + "_i";
    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.innerHTML =
      `<div class="msg-row">` +
      `<div class="bot-av">⚙</div>` +
      `<div class="think-wrap">` +
      `<div class="tk-hdr" id="${hid}" onclick="turns['${this.id}'].toggle()">` +
      `<div class="tk-star" id="${iid}">${SPIN_SVG}</div>` +
      `<span class="tk-title" id="${tid}">Working…</span>` +
      `<span class="tk-chev">▼</span>` +
      `</div>` +
      `<div class="tk-steps" id="${sid}"></div>` +
      `</div></div>`;
    ci.appendChild(wrap);
    this.stepsEl = document.getElementById(sid);
    sc();
  }

  toggle() {
    this.collapsed = !this.collapsed;
    const steps = document.getElementById(this.id + "_s");
    const hdr   = document.getElementById(this.id + "_h");
    if (steps) steps.classList.toggle("collapsed", this.collapsed);
    if (hdr)   hdr.classList.toggle("collapsed",   this.collapsed);
    const chev = hdr && hdr.querySelector(".tk-chev");
    if (chev) chev.textContent = this.collapsed ? "▶" : "▼";
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
    el.innerHTML =
      `<div class="tk-ico">${icon}</div>` +
      `<div class="tk-info">` +
      `<span class="tk-lbl">${esc(label)}</span>` +
      (tag ? `<span class="tk-tag">${esc(tag)}</span>` : "") +
      `</div>`;
    this.stepsEl.appendChild(el);
    sc();
  }

  addSearching(query) {
    if (!this.stepsEl) return;
    const el = document.createElement("div");
    el.className = "tk-step";
    el.innerHTML =
      `<div class="tk-ico">${TOOL_ICO.internet_search}</div>` +
      `<div class="tk-info" style="flex:1">` +
      `<span class="tk-lbl">Searching the web</span>` +
      `<span class="tk-tag">${esc(String(query).slice(0,55))}</span>` +
      `</div>` +
      `<div class="tk-dots"><span></span><span></span><span></span></div>`;
    this.stepsEl.appendChild(el);
    sc();
  }

  addDone() {
    if (!this.stepsEl) return;
    const el = document.createElement("div");
    el.className = "tk-step";
    el.innerHTML =
      `<div class="tk-ico tk-check">${DONE_SVG}</div>` +
      `<div class="tk-info"><span class="tk-lbl" style="color:var(--green-mid)">Got response</span></div>`;
    this.stepsEl.appendChild(el);
    sc();
  }

  finish() {
    const ico = document.getElementById(this.id + "_i");
    const ttl = document.getElementById(this.id + "_t");
    if (ico) { ico.innerHTML = DONE_SVG; ico.classList.add("done"); }
    if (ttl) ttl.textContent = this.toolsUsed.length
      ? "Used: " + this.toolsUsed.join(", ") : "Done";
    setTimeout(() => { if (!this.collapsed) this.toggle(); }, 700);
  }

  initBubble() {
    if (this.bubbleEl) return;
    const bid  = this.id + "_b";
    const tsid = this.id + "_ts";
    const wrap = document.createElement("div");
    wrap.className = "msg bot";
    wrap.innerHTML =
      `<div class="msg-row">` +
      `<div class="bot-av">⚙</div>` +
      `<div class="bubble md" id="${bid}"><span class="cur"></span></div>` +
      `</div>` +
      `<div class="msg-ts" id="${tsid}"></div>`;
    ci.appendChild(wrap);
    this.bubbleEl = document.getElementById(bid);
    this.tsEl     = document.getElementById(tsid);
    sc();
  }

  stream(text) {
    if (this.bubbleEl)
      this.bubbleEl.innerHTML = md(text) + '<span class="cur"></span>';
    sc();
  }

  finalize(text) {
    if (this.bubbleEl) this.bubbleEl.innerHTML = md(text);
    if (this.tsEl)     this.tsEl.textContent = tstr();
    sc();
  }
}

const turns = {};

// ── User bubble ───────────────────────────────────────────────────────────────
function addUser(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML =
    `<div class="msg-row"><div class="bubble">${esc(text)}</div></div>` +
    `<div class="msg-ts">${tstr()}</div>`;
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
    if (i % 6 === 5) await wait(10);
  }
  turn.finalize(text);
}

// ── Send ──────────────────────────────────────────────────────────────────────
async function send() {
  const query = qEl.value.trim();
  if (!query) return;
  qEl.value = "";
  qEl.style.height = "24px";
  sbtn.disabled = true;

  addUser(query);
  dlog("info", "→ " + query);

  const turn = new Turn();
  turns[turn.id] = turn;
  let answer = "";

  try {
    const resp = await fetch(`${SERVER}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);

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

        let evt;
        try { evt = JSON.parse(raw); } catch { continue; }

        switch (evt.type) {

          case "debug":
            dlog("info", evt.text);
            if (!turn.hasThink) {
              turn.initThink();
              if (evt.text.includes("conversation") || evt.text.includes("directly")) {
                turn.setTitle("Thinking…");
                turn.isDirect = true;
              }
            }
            break;

          case "tool_call":
            if (!turn.hasThink) turn.initThink();
            turn.toolsUsed.push(evt.name);
            dlog("tool", "→ " + evt.name + "(" + JSON.stringify(evt.args) + ")");
            if (evt.name === "internet_search") {
              turn.addSearching(evt.args && evt.args.query ? evt.args.query : query);
              turn.setTitle("Searching the web…");
            } else {
              const label = TOOL_LABELS[evt.name] || evt.name;
              const tag   = Object.values(evt.args || {}).join(", ").slice(0, 55) || null;
              turn.addStep(evt.name, label, tag);
              turn.setTitle("Using " + evt.name + "…");
            }
            break;

          case "tool_result":
            dlog("result", "← " + evt.name + ": " + evt.result);
            if (turn.hasThink) turn.addDone();
            break;

          case "answer":
            answer = evt.text;
            dlog("answer", answer.length + " chars");
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
            turn.finalize("⚠ " + evt.text);
            break;
        }
      }
    }

    if (!answer) {
      if (turn.hasThink) turn.finish();
      turn.initBubble();
      turn.finalize("(no response)");
    }

  } catch (e) {
    if (turn.hasThink) turn.finish();
    turn.initBubble();
    turn.finalize("⚠ " + e.message);
    dlog("error", e.message);
    document.getElementById("abadge").className = "badge off";
    document.getElementById("abadge").textContent = "OFFLINE";
  } finally {
    setTimeout(() => { delete turns[turn.id]; }, 30000);
    sbtn.disabled = false;
    qEl.focus();
  }
}

// ── Textarea ──────────────────────────────────────────────────────────────────
qEl.addEventListener("input", () => {
  qEl.style.height = "24px";
  qEl.style.height = Math.min(qEl.scrollHeight, 130) + "px";
});
qEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

function fill(t) {
  qEl.value = t;
  qEl.focus();
  qEl.dispatchEvent(new Event("input"));
}

checkHealth();
setInterval(checkHealth, 30000);