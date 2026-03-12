// ── Config ────────────────────────────────────────────────────────────────────
const SERVER = (new URLSearchParams(location.search).get("server"))
  || (typeof window.MCP_SERVER_URL !== "undefined" ? window.MCP_SERVER_URL : null)
  || `${location.protocol}//${location.hostname}:8000`;

// ── Conversation history (sent with every request for context) ────────────────
// Each entry: { role: "user"|"assistant", content: string }
const chatHistory = [];
const MAX_HISTORY = 20; // keep last 20 turns (10 pairs)

// ── DOM refs ──────────────────────────────────────────────────────────────────
const ci     = document.getElementById("ci");
const chatEl = document.getElementById("chat");
const qEl    = document.getElementById("q");
const sbtn   = document.getElementById("sbtn");
const dLog   = document.getElementById("dbg-log");
let dbgOpen  = false;

function toggleDbg() {
  dbgOpen = !dbgOpen;
  document.getElementById("dbg").classList.toggle("open", dbgOpen);
  document.getElementById("chat-wrap").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("ibar").classList.toggle("dbg-open", dbgOpen);
  document.getElementById("dbgbtn").classList.toggle("active", dbgOpen);
  document.getElementById("te").classList.toggle("active", dbgOpen);
  document.getElementById("tc").classList.toggle("active", !dbgOpen);
}

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
  const blocks = [];
  let text = raw.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push({ lang: (lang || "code").trim(), code: code.trimEnd() });
    return "\x00BLOCK" + (blocks.length - 1) + "\x00";
  });
  text = text.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  text = text.replace(/\*\*\*(.+?)\*\*\*/g,"<strong><em>$1</em></strong>");
  text = text.replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");
  text = text.replace(/\*(\S[^*]*?\S|\S)\*/g,"<em>$1</em>");
  text = text.replace(/`([^`\n]+)`/g,'<code class="icode">$1</code>');
  const lines = text.split("\n");
  const out = []; let inList = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\x00BLOCK(\d+)\x00$/.test(line)) {
      if (inList) { out.push("</ul>"); inList = false; }
      const idx = parseInt(line.match(/\d+/)[0]);
      const { lang, code } = blocks[idx];
      const escaped = code.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
      out.push(`<div class="code-block"><div class="code-hdr"><span class="code-lang">${esc(lang)}</span><button class="code-copy" onclick="copyCode(this)">Copy</button></div><pre>${escaped}</pre></div>`);
      continue;
    }
    if (/^### /.test(line)) { out.push(`<h4>${line.slice(4)}</h4>`); continue; }
    if (/^## /.test(line))  { out.push(`<h3>${line.slice(3)}</h3>`); continue; }
    if (/^# /.test(line))   { out.push(`<h2>${line.slice(2)}</h2>`); continue; }
    const bullet = line.match(/^[ \t]*[-*•] (.+)/);
    if (bullet) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${bullet[1]}</li>`); continue; }
    const numbered = line.match(/^(\d+)\. (.+)/);
    if (numbered) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${numbered[1]}. ${numbered[2]}</li>`); continue; }
    if (inList && line.trim() === "") { out.push("</ul>"); inList = false; out.push("<br>"); continue; }
    const kv = line.match(/^([ \t]*)([a-zA-Z][\w\s]{1,25}?)\s*:\s*(.+)$/);
    if (kv && !line.startsWith("http") && !line.includes("://")) {
      out.push(`<div class="kv-row"><span class="kv-key">${kv[2].trim()}</span><span class="kv-val">${kv[3]}</span></div>`);
      continue;
    }
    if (line.trim() === "") { if (out.length && out[out.length-1] !== "<br>") out.push("<br>"); continue; }
    out.push(`<span>${line}</span><br>`);
  }
  if (inList) out.push("</ul>");
  return out.join("\n");
}

// ── SVG icons ─────────────────────────────────────────────────────────────────
const SPIN_SVG = `<svg viewBox="0 0 24 24" fill="none"><path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07" stroke="var(--green-mid)" stroke-width="2" stroke-linecap="round"/></svg>`;
const DONE_SVG = `<svg viewBox="0 0 20 20" fill="none"><path d="M4 10l4 4 8-8" stroke="var(--green-mid)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const TOOL_ICO = {
  internet_search:  `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 3c-2 2-2 12 0 14M10 3c2 2 2 12 0 14M3 10h14" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  get_weather:      `<svg viewBox="0 0 20 20" fill="none"><path d="M4 13a4 4 0 110-8 5.5 5.5 0 019 1.5A3 3 0 1116 13H4z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  get_current_time: `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  read_doc_content: `<svg viewBox="0 0 20 20" fill="none"><rect x="4" y="2" width="12" height="16" rx="2" stroke="#8e8e93" stroke-width="1.5"/><path d="M7 7h6M7 10h6M7 13h4" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  edit_doc_content: `<svg viewBox="0 0 20 20" fill="none"><path d="M4 16l3-1 9-9-2-2-9 9-1 3z" stroke="#8e8e93" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  _default:         `<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="6" stroke="#8e8e93" stroke-width="1.5"/><path d="M10 7v3l2 2" stroke="#8e8e93" stroke-width="1.5" stroke-linecap="round"/></svg>`,
};
const TOOL_LABELS = {
  get_weather: "Checking weather", get_current_time: "Getting current time",
  read_doc_content: "Reading document", edit_doc_content: "Editing document",
  internet_search: "Searching the web",
};

// ══════════════════════════════════════════════════════════════════════════════
//  Turn
// ══════════════════════════════════════════════════════════════════════════════
class Turn {
  constructor() {
    this.id=uid(); this.stepsEl=null; this.bubbleEl=null; this.tsEl=null;
    this.collapsed=false; this.toolsUsed=[]; this.hasThink=false; this.isDirect=false;
  }
  initThink() {
    if (this.hasThink) return; this.hasThink=true;
    const sid=this.id+"_s",hid=this.id+"_h",tid=this.id+"_t",iid=this.id+"_i";
    const wrap=document.createElement("div"); wrap.className="msg bot";
    wrap.innerHTML=`<div class="msg-row"><div class="bot-av">⚙</div><div class="think-wrap"><div class="tk-hdr" id="${hid}" onclick="turns['${this.id}'].toggle()"><div class="tk-star" id="${iid}">${SPIN_SVG}</div><span class="tk-title" id="${tid}">Working…</span><span class="tk-chev">▼</span></div><div class="tk-steps" id="${sid}"></div></div></div>`;
    ci.appendChild(wrap); this.stepsEl=document.getElementById(sid); sc();
  }
  toggle() {
    this.collapsed=!this.collapsed;
    const steps=document.getElementById(this.id+"_s"),hdr=document.getElementById(this.id+"_h");
    if(steps)steps.classList.toggle("collapsed",this.collapsed);
    if(hdr)hdr.classList.toggle("collapsed",this.collapsed);
    const chev=hdr&&hdr.querySelector(".tk-chev");
    if(chev)chev.textContent=this.collapsed?"▶":"▼";
  }
  setTitle(t){const el=document.getElementById(this.id+"_t");if(el)el.textContent=t;}
  addStep(toolName,label,tag){
    if(!this.stepsEl)return;
    const icon=TOOL_ICO[toolName]||TOOL_ICO._default;
    const el=document.createElement("div"); el.className="tk-step";
    el.innerHTML=`<div class="tk-ico">${icon}</div><div class="tk-info"><span class="tk-lbl">${esc(label)}</span>${tag?`<span class="tk-tag">${esc(tag)}</span>`:""}</div>`;
    this.stepsEl.appendChild(el); sc();
  }
  addSearching(query){
    if(!this.stepsEl)return;
    const el=document.createElement("div"); el.className="tk-step";
    el.innerHTML=`<div class="tk-ico">${TOOL_ICO.internet_search}</div><div class="tk-info" style="flex:1"><span class="tk-lbl">Searching the web</span><span class="tk-tag">${esc(String(query).slice(0,55))}</span></div><div class="tk-dots"><span></span><span></span><span></span></div>`;
    this.stepsEl.appendChild(el); sc();
  }
  addDone(){
    if(!this.stepsEl)return;
    const el=document.createElement("div"); el.className="tk-step";
    el.innerHTML=`<div class="tk-ico tk-check">${DONE_SVG}</div><div class="tk-info"><span class="tk-lbl" style="color:var(--green-mid)">Got response</span></div>`;
    this.stepsEl.appendChild(el); sc();
  }
  finish(){
    const ico=document.getElementById(this.id+"_i"),ttl=document.getElementById(this.id+"_t");
    if(ico){ico.innerHTML=DONE_SVG;ico.classList.add("done");}
    if(ttl)ttl.textContent=this.toolsUsed.length?"Used: "+this.toolsUsed.join(", "):"Done";
    setTimeout(()=>{if(!this.collapsed)this.toggle();},700);
  }
  initBubble(){
    if(this.bubbleEl)return;
    const bid=this.id+"_b",tsid=this.id+"_ts";
    const wrap=document.createElement("div"); wrap.className="msg bot";
    wrap.innerHTML=`<div class="msg-row"><div class="bot-av">⚙</div><div class="bubble md" id="${bid}"><span class="cur"></span></div></div><div class="msg-ts" id="${tsid}"></div>`;
    ci.appendChild(wrap); this.bubbleEl=document.getElementById(bid); this.tsEl=document.getElementById(tsid); sc();
  }
  stream(text){if(this.bubbleEl)this.bubbleEl.innerHTML=md(text)+'<span class="cur"></span>';sc();}
  finalize(text){if(this.bubbleEl)this.bubbleEl.innerHTML=md(text);if(this.tsEl)this.tsEl.textContent=tstr();sc();}
}
const turns={};

function addUser(text){
  const el=document.createElement("div"); el.className="msg user";
  el.innerHTML=`<div class="msg-row"><div class="bubble">${esc(text)}</div></div><div class="msg-ts">${tstr()}</div>`;
  ci.appendChild(el); sc();
}

async function streamWords(turn,text){
  turn.initBubble();
  const words=text.split(" "); let built="";
  for(let i=0;i<words.length;i++){
    built+=(i>0?" ":"")+words[i]; turn.stream(built);
    if(i%6===5)await wait(10);
  }
  turn.finalize(text);
}

// ── Slash command definitions ─────────────────────────────────────────────────
const SLASH_TOOLS = [
  {
    cmd:"search", name:"/search", desc:"Search the web for anything",
    icon:`<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="var(--green-mid)" stroke-width="1.5"/><path d="M10 3c-2 2-2 12 0 14M10 3c2 2 2 12 0 14M3 10h14" stroke="var(--green-mid)" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    badge:"internet_search", placeholder:"Search the web for…",
    // Explicit instruction so LLM can't pick wrong tool
    template: q => `Search the web for: ${q}`,
    toolHint: "internet_search",
  },
  {
    cmd:"weather", name:"/weather", desc:"Get weather for any city",
    icon:`<svg viewBox="0 0 20 20" fill="none"><path d="M4 13a4 4 0 110-8 5.5 5.5 0 019 1.5A3 3 0 1116 13H4z" stroke="var(--green-mid)" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
    badge:"get_weather", placeholder:"City name…",
    template: q => `What is the current weather in ${q}?`,
    toolHint: "get_weather",
  },
  {
    cmd:"time", name:"/time", desc:"Get current time in any timezone",
    icon:`<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="var(--green-mid)" stroke-width="1.5"/><path d="M10 6v4l3 2" stroke="var(--green-mid)" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    badge:"get_current_time", placeholder:"Timezone or city e.g. Tokyo, UTC…",
    template: q => q ? `What is the current time in ${q}?` : "What is the current time right now?",
    toolHint: "get_current_time",
  },
  {
    cmd:"read", name:"/read", desc:"Read a document by ID",
    icon:`<svg viewBox="0 0 20 20" fill="none"><rect x="4" y="2" width="12" height="16" rx="2" stroke="var(--green-mid)" stroke-width="1.5"/><path d="M7 7h6M7 10h6M7 13h4" stroke="var(--green-mid)" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    badge:"read_doc_content", placeholder:"Document ID e.g. report.pdf…",
    template: q => `Use the read_doc_content tool to read this document: ${q}`,
    toolHint: "read_doc_content",
  },
  {
    cmd:"news", name:"/news", desc:"Get latest news on a topic",
    icon:`<svg viewBox="0 0 20 20" fill="none"><rect x="2" y="4" width="16" height="12" rx="2" stroke="var(--green-mid)" stroke-width="1.5"/><path d="M5 8h10M5 11h6" stroke="var(--green-mid)" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    badge:"internet_search", placeholder:"Topic e.g. India, AI, stocks…",
    template: q => `Search the web for the latest news today about: ${q}`,
    toolHint: "internet_search",
  },
];

// ── Slash menu state ──────────────────────────────────────────────────────────
let slashActive=false, slashIdx=0, slashTool=null, slashFiltered=[];
const slashMenu=document.getElementById("slash-menu");
const slashList=document.getElementById("slash-list");

function renderSlashMenu(filter=""){
  const q=filter.toLowerCase().replace(/^\//,"");
  slashFiltered=q
    ? SLASH_TOOLS.filter(t=>t.cmd.startsWith(q)||t.desc.toLowerCase().includes(q))
    : SLASH_TOOLS;
  slashList.innerHTML="";
  if(!slashFiltered.length){closeSlash();return;}
  slashFiltered.forEach((t,i)=>{
    const el=document.createElement("button");
    el.className="slash-item"+(i===slashIdx?" active":"");
    el.innerHTML=`<div class="slash-icon">${t.icon}</div><div class="slash-info"><span class="slash-name">${t.name}</span><span class="slash-desc">${t.desc}</span></div><span class="slash-badge">${t.badge}</span>`;
    el.addEventListener("mousedown",e=>{e.preventDefault();selectSlashTool(t);});
    slashList.appendChild(el);
  });
  slashMenu.style.display="block"; slashActive=true;
}

function highlightSlash(idx){
  slashIdx=(idx+slashFiltered.length)%slashFiltered.length;
  Array.from(slashList.children).forEach((el,i)=>el.classList.toggle("active",i===slashIdx));
}

const pillWrap = document.getElementById("tool-pill-wrap");

function showToolPill(tool){
  // Render a coloured pill with the tool icon + name + ✕ dismiss
  const icon = tool.icon.replace(/stroke="var\(--green-mid\)"/g, 'stroke="currentColor"');
  pillWrap.innerHTML =
    `<div class="tool-pill">` +
    `<span class="tool-pill-icon">${icon}</span>` +
    `<span>${tool.name}</span>` +
    `<i class="tool-pill-x" title="Clear" onclick="clearToolPill()">✕</i>` +
    `</div>`;
  pillWrap.style.display = "flex";
}

function clearToolPill(){
  pillWrap.innerHTML = "";
  pillWrap.style.display = "none";
}

function selectSlashTool(tool){
  slashTool=tool; slashActive=false; slashMenu.style.display="none";
  // Clear the "/cmd" text — user only types the argument now
  qEl.value="";
  qEl.placeholder=tool.placeholder;
  showToolPill(tool);
  qEl.focus(); qEl.dispatchEvent(new Event("input"));
}

function closeSlash(){slashMenu.style.display="none";slashActive=false;}

function resetSlash(){
  slashTool=null; slashActive=false; slashMenu.style.display="none";
  qEl.placeholder="Ask anything… or type / for tools";
  clearToolPill();
}

// ── Input listeners ───────────────────────────────────────────────────────────
qEl.addEventListener("input",()=>{
  qEl.style.height="24px";
  qEl.style.height=Math.min(qEl.scrollHeight,130)+"px";
  const val=qEl.value;
  // If pill is active, textarea = argument only — never show slash menu
  if(slashTool) return;
  if(!val){resetSlash();return;}
  if(val.startsWith("/")){slashIdx=0;renderSlashMenu(val.slice(1));return;}
  closeSlash();
});

qEl.addEventListener("keydown",e=>{
  if(slashActive){
    if(e.key==="ArrowDown"){e.preventDefault();highlightSlash(slashIdx+1);return;}
    if(e.key==="ArrowUp")  {e.preventDefault();highlightSlash(slashIdx-1);return;}
    if(e.key==="Escape")   {e.preventDefault();closeSlash();qEl.value="";resetSlash();return;}
    if(e.key==="Tab"||e.key==="Enter"){
      e.preventDefault();
      if(slashFiltered[slashIdx])selectSlashTool(slashFiltered[slashIdx]);
      return;
    }
  }
  if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}
});

document.addEventListener("mousedown",e=>{
  if(!slashMenu.contains(e.target)&&e.target!==qEl)closeSlash();
});

// ── Send ──────────────────────────────────────────────────────────────────────
async function send(){
  let raw=qEl.value.trim();
  if(!raw)return;

  let query=raw, forceTools=false, toolHint=null;

  if(slashTool){
    // raw IS the argument — no prefix stripping needed (pill holds the cmd)
    const arg = raw.trim();

    // Guard: require argument for all except /time
    if(!arg && slashTool.cmd !== "time"){
      qEl.placeholder="⚠ Please enter a value first…";
      setTimeout(()=>{qEl.placeholder=slashTool.placeholder;},2000);
      return;
    }

    query      = slashTool.template(arg);
    forceTools = true;
    toolHint   = slashTool.toolHint;
    dlog("info",`[slash] /${slashTool.cmd} → tool_hint=${toolHint}`);
  }

  qEl.value=""; qEl.style.height="24px";
  resetSlash(); sbtn.disabled=true;

  // Show pill name + arg in user bubble (e.g. "/search kimi2.5")
  const displayText = slashTool ? `/${slashTool.cmd} ${raw}`.trim() : raw;
  addUser(displayText);
  dlog("info","→ "+query);

  // Add to history BEFORE the request
  chatHistory.push({role:"user", content:query});
  if(chatHistory.length > MAX_HISTORY) chatHistory.splice(0, chatHistory.length - MAX_HISTORY);

  const turn=new Turn(); turns[turn.id]=turn; let answer=""; let tokenBuf="";

  try{
    const resp=await fetch(`${SERVER}/chat/stream`,{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        query,
        force_tools: forceTools,
        tool_hint:   toolHint,          // ← new: preferred tool name
        history:     chatHistory.slice(0,-1), // send history EXCLUDING current msg
      }),
    });
    if(!resp.ok)throw new Error("HTTP "+resp.status);

    const reader=resp.body.getReader();
    const decoder=new TextDecoder();
    let buf="";

    while(true){
      const{done,value}=await reader.read();
      if(done)break;
      buf+=decoder.decode(value,{stream:true});
      const lines=buf.split("\n");
      buf=lines.pop();

      for(const line of lines){
        if(!line.startsWith("data: "))continue;
        const raw=line.slice(6).trim();
        if(raw==="[DONE]")break;
        let evt; try{evt=JSON.parse(raw);}catch{continue;}

        switch(evt.type){
          case"debug":
            dlog("info",evt.text);
            if(!turn.hasThink){
              turn.initThink();
              if(evt.text.includes("conversation")||evt.text.includes("directly")){
                turn.setTitle("Thinking…");turn.isDirect=true;
              }
            }
            break;
          case"tool_call":
            if(!turn.hasThink)turn.initThink();
            turn.toolsUsed.push(evt.name);
            dlog("tool","→ "+evt.name+"("+JSON.stringify(evt.args)+")");
            if(evt.name==="internet_search"){
              turn.addSearching(evt.args&&evt.args.query?evt.args.query:query);
              turn.setTitle("Searching the web…");
            }else{
              const label=TOOL_LABELS[evt.name]||evt.name;
              const tag=Object.values(evt.args||{}).join(", ").slice(0,55)||null;
              turn.addStep(evt.name,label,tag);
              turn.setTitle("Using "+evt.name+"…");
            }
            break;
          case"tool_result":
            dlog("result","← "+evt.name+": "+evt.result);
            if(turn.hasThink)turn.addDone();
            break;
          case"token":
            // Live token streaming — show words as they arrive from the LLM
            tokenBuf += evt.text;
            if(!turn.bubbleEl){
              // Collapse thinking panel immediately on first token
              if(turn.hasThink) turn.finish();
              turn.initBubble();
            }
            turn.stream(tokenBuf);
            break;

          case"answer":
            answer=evt.text;
            dlog("answer",answer.length+" chars");
            if(tokenBuf){
              // Already streamed live — just finalize (no re-stream needed)
              turn.finalize(answer);
            } else {
              // Fallback: no tokens received, do word-by-word stream
              if(turn.hasThink){turn.finish();await wait(750);}
              await streamWords(turn,answer);
            }
            break;
          case"error":
            dlog("error",evt.text);
            if(turn.hasThink)turn.finish();
            turn.initBubble();turn.finalize("⚠ "+evt.text);
            break;
        }
      }
    }

    if(!answer){
      if(turn.hasThink)turn.finish();
      turn.initBubble();turn.finalize("(no response)");
    }else{
      // Save assistant reply to history
      chatHistory.push({role:"assistant", content:answer});
      if(chatHistory.length > MAX_HISTORY) chatHistory.splice(0, chatHistory.length - MAX_HISTORY);
    }

  }catch(e){
    if(turn.hasThink)turn.finish();
    turn.initBubble();turn.finalize("⚠ "+e.message);
    dlog("error",e.message);
    document.getElementById("abadge").className="badge off";
    document.getElementById("abadge").textContent="OFFLINE";
    // Pop the user message we added, since it failed
    chatHistory.pop();
  }finally{
    setTimeout(()=>{delete turns[turn.id];},30000);
    sbtn.disabled=false; qEl.focus();
  }
}

function fill(t){qEl.value=t;qEl.focus();qEl.dispatchEvent(new Event("input"));}

checkHealth();
setInterval(checkHealth,30000);