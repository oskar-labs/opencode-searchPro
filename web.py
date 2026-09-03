#!/usr/bin/env python3
r"""
SearchPro Web — Beautiful local UI for opencode prompt search
Serves http://127.0.0.1:8765 — queries the opencode SQLite DB (read-only).
DB location: $OPENCODE_DB, else ~/.local/share/opencode/opencode.db

Run: python web.py
Open: http://127.0.0.1:8765
"""
import http.server, socketserver, urllib.parse, json, sqlite3, pathlib, datetime, os, re, base64, sys, time, threading

DB = os.environ.get("OPENCODE_DB") or str(pathlib.Path.home() / ".local" / "share" / "opencode" / "opencode.db")
PORT = 8765
BASE_DIR = pathlib.Path(__file__).resolve().parent
HTML_PATH = BASE_DIR / "index.html"

def get_html():
    """Read index.html from disk every request — edit + refresh, no restart. Falls back to embedded HTML."""
    try:
        return HTML_PATH.read_text(encoding="utf-8")
    except Exception:
        return HTML  # embedded fallback (defined below)

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>OpenCode SearchPro — opencode prompts</title>
<script>
  // Mild dark: respect system on first visit, then the toggle overrides it (stored in localStorage)
  const dm = localStorage.getItem('searchpro-dark');
  if (dm === '1' || (!dm && window.matchMedia('(prefers-color-scheme: dark)').matches)) document.documentElement.classList.add('dark');
</script>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config = {darkMode: 'class'};</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
<style>
*{font-family:Inter,system-ui,sans-serif}
.mono{font-family:JetBrains Mono,monospace}
.card{transition:all .2s ease}
.card:hover{transform:translateY(-1px);box-shadow:0 10px 30px rgba(0,0,0,.08);border-color:#d4d4d8}
.dark .card:hover{box-shadow:0 8px 30px rgba(0,0,0,.35);border-color:#52525b}
.glass{backdrop-filter:blur(12px)}
.fold{display:grid;grid-template-rows:0fr;transition:grid-template-rows .25s ease}
.fold.open{grid-template-rows:1fr}
.fold>*{overflow:hidden;min-height:0}
.fold:not(.open)>*{padding-top:0 !important;padding-bottom:0 !important}
html{scroll-behavior:smooth}
::selection{background:#93b4d8;color:#111}
.dark ::selection{background:#52525b;color:#fff}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:#d4d4d8;border-radius:999px}
.dark ::-webkit-scrollbar-thumb{background:#3f3f46}
::-webkit-scrollbar-thumb:hover{background:#a1a1aa}
.dark ::-webkit-scrollbar-thumb:hover{background:#52525b}
/* 20% larger UI */
html{font-size:120%}
body{zoom:1.2; transform-origin: top center}
@media (max-width: 768px){ body{zoom:1.15} }
</style>
</head>
<body class="bg-[#c2c8d0] dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 min-h-screen transition-colors">
<!-- Header -->
<div class="sticky top-0 z-20 glass bg-white/85 dark:bg-zinc-900/80 border-b border-zinc-200 dark:border-zinc-800">
  <div class="max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-zinc-400 to-zinc-700 dark:from-zinc-700 dark:to-zinc-400 flex items-center justify-center text-white font-bold text-sm">Sp</div>
      <div>
        <h1 class="font-semibold tracking-tight text-[15px] dark:text-white">OpenCode SearchPro</h1>
        <p class="text-xs text-zinc-500 dark:text-zinc-400 -mt-0.5">OpenCode native DB (WAL-safe read-only) • <span id="dbsize">—</span> • query <span id="ms" class="mono">—</span></p>
      </div>
    </div>
    <div class="flex items-center gap-2 text-xs">
      <button id="darkToggle" title="Toggle dark" class="w-8 h-8 rounded-full border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 flex items-center justify-center text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700">◐</button>
      <span class="hidden sm:inline-flex px-2.5 py-1 rounded-full bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300" id="projCount">— projects</span>
    </div>
  </div>
</div>

<div class="max-w-6xl mx-auto px-6 py-6">
  <!-- Search Bar -->
  <div class="bg-white dark:bg-zinc-800 rounded-2xl border border-zinc-200 dark:border-zinc-700 p-4 sm:p-5 shadow-[0_2px_20px_rgba(0,0,0,.05)]">
    <div class="flex flex-col sm:flex-row gap-3">
      <div class="flex-1 relative">
        <svg class="absolute left-3.5 top-3 w-4 h-4 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        <input id="q" placeholder="Search prompts…  e.g. rate limit, caching, webhook" class="w-full pl-10 pr-4 py-2.5 rounded-xl border border-zinc-300 dark:border-zinc-600 bg-zinc-100 dark:bg-zinc-900 focus:bg-white dark:focus:bg-zinc-900 focus:border-zinc-400 focus:ring-4 focus:ring-zinc-200 dark:focus:ring-emerald-900/30 outline-none text-sm placeholder:text-zinc-400 dark:text-zinc-100"/>
      </div>
      <select id="project" class="px-3 py-2.5 rounded-xl border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 text-sm dark:text-zinc-100 min-w-[180px]">
        <option value="">All projects</option>
      </select>
      <select id="limit" class="px-3 py-2.5 rounded-xl border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 text-sm dark:text-zinc-100">
        <option value="20">20 results</option>
        <option value="50">50 results</option>
        <option value="100">100 results</option>
      </select>
    </div>
    <div class="mt-5 flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
      <span>Press <kbd class="px-1.5 py-0.5 bg-zinc-200 dark:bg-zinc-700 border border-zinc-300 dark:border-zinc-600 rounded text-[10px]">/</kbd> to focus • <span id="status">ready</span></span>
      <span class="hidden sm:inline">Tip: reasoning & tool calls are never searched</span>
    </div>
    <div class="mt-4 pt-4 border-t border-zinc-200 dark:border-zinc-700 flex items-center gap-4 text-xs text-zinc-600 dark:text-zinc-300">
      <span class="text-zinc-500 dark:text-zinc-400">Searching in :</span>
      <label class="inline-flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="roleUser" checked class="accent-zinc-600 w-3.5 h-3.5"/> User entries</label>
      <span class="text-zinc-500 dark:text-zinc-400">and/or</span>
      <label class="inline-flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="roleAssistant" class="accent-zinc-600 w-3.5 h-3.5"/> Agent responses</label>
    </div>
  </div>

  <!-- Models panel -->
  <div class="mt-3 bg-white dark:bg-zinc-800 rounded-2xl border border-zinc-200 dark:border-zinc-700 shadow-[0_2px_20px_rgba(0,0,0,.05)] overflow-hidden">
    <button id="modelsToggle" class="w-full px-4 sm:px-5 py-3 flex items-center justify-between text-sm hover:bg-zinc-100 dark:hover:bg-zinc-700/50 transition-colors">
      <span class="font-medium">Model usage statistics <span class="text-xs font-normal text-zinc-500 dark:text-zinc-400">— user prompts per LLM</span></span>
      <svg id="modelsChevron" class="w-4 h-4 text-zinc-400 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div id="modelsBody" class="fold"><div id="modelsBars" class="px-4 sm:px-5 pb-4 grid gap-2.5"></div></div>
  </div>

  <!-- Results -->
  <div id="results" class="mt-6 grid gap-3"></div>
  <div id="empty" class="hidden mt-16 text-center">
    <div class="w-12 h-12 mx-auto rounded-2xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 flex items-center justify-center">🔍</div>
    <p class="mt-3 text-sm text-zinc-600 dark:text-zinc-300">No prompts match</p>
    <p class="text-xs text-zinc-400">Try a broader term or switch project</p>
  </div>
</div>

<div class="max-w-6xl mx-auto px-6 pb-8 text-center text-[11px] text-zinc-400 dark:text-zinc-500">
  Local DB: <span id="dbpath" title="">…</span> • WAL-safe read-only • <a class="underline" href="https://github.com/anomalyco/opencode" target="_blank">opencode</a>
</div>

<script>
const q = document.getElementById('q');
const project = document.getElementById('project');
const limit = document.getElementById('limit');
const roleUser = document.getElementById('roleUser');
const roleAssistant = document.getElementById('roleAssistant');
const results = document.getElementById('results');
const empty = document.getElementById('empty');
const status = document.getElementById('status');
const projCountEl = document.getElementById('projCount');

let timer;
let msSamples = [];
function debounce(fn, ms){ clearTimeout(timer); timer=setTimeout(fn,ms); }

async function loadProjects(){
  try{
    const r = await fetch('/api/projects');
    const data = await r.json();
    data.forEach(p=>{
      const o=document.createElement('option');
      o.value=p;
      o.textContent = p.length>50 ? '…/'+p.split('/').slice(-2).join('/') : p;
      o.title=p;
      project.appendChild(o);
    });
    projCountEl.textContent = data.length + ' projects';
  }catch{}
}

async function loadStats(){
  try{
    const r = await fetch('/api/stats');
    const s = await r.json();
    document.getElementById('dbsize').textContent = `${s.db_mb.toLocaleString('en-US')} MB`;
    const dbp = document.getElementById('dbpath');
    if(dbp && s.db_path){ dbp.textContent = s.db_path; dbp.title = s.db_path; }
  }catch{}
}

const escA = s => (s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
function highlight(text, query, tip){
  if(!query) return text;
  const esc = query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const tipAttr = tip ? ` data-tip="${escA(tip)}"` : '';
  return text.replace(new RegExp(`(${esc})`,'gi'), `<mark${tipAttr} class="bg-amber-100 dark:bg-amber-900/40 dark:text-amber-200 text-amber-900 px-0.5 rounded underline decoration-2 underline-offset-4 decoration-amber-400 dark:decoration-amber-500">$1</mark>`);
}

function selectedRoles(){
  const r=[];
  if(roleUser.checked) r.push('user');
  if(roleAssistant.checked) r.push('assistant');
  return r.length ? r : ['user'];
}

const fmtD = ms => { const d = new Date(ms||0); const p = n => String(n).padStart(2,'0'); return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`; };

const BM_KEY='searchpro-bookmarks';
const rendered = new Map();
const getBM=()=>{ try{ return JSON.parse(localStorage.getItem(BM_KEY))||[]; }catch{ return []; } };
const saveBM=b=>localStorage.setItem(BM_KEY, JSON.stringify(b));
function toggleBM(item){
  let b=getBM();
  if(b.some(x=>x.mid===item.messageID)) b=b.filter(x=>x.mid!==item.messageID);
  else b.push({mid:item.messageID, sid:item.sessionID, title:item.title, project:item.project, role:item.role, time:item.time, snippet:item.snippet, context:item.context||''});
  saveBM(b);
  return b.some(x=>x.mid===item.messageID);
}
function paintBM(btn, marked){
  btn.title = marked ? 'Remove bookmark' : 'Bookmark this';
  btn.className = 'bm absolute top-3 right-3 w-7 h-7 rounded-full border flex items-center justify-center hover:scale-110 transition shrink-0 ' + (marked
    ? 'bg-amber-100 border-amber-300 text-amber-600 dark:bg-amber-900/40 dark:border-amber-700 dark:text-amber-300'
    : 'bg-white/70 border-zinc-200 text-zinc-400 dark:bg-zinc-900/70 dark:border-zinc-700 dark:text-zinc-500');
  btn.querySelector('svg').setAttribute('fill', marked ? 'currentColor' : 'none');
}
function fixDivider(){
  results.querySelectorAll('.bmdiv').forEach(d=>d.remove());
  const cards=[...results.querySelectorAll('.card')];
  const firstPlain=cards.find(c=>!c.classList.contains('marked'));
  if(firstPlain && cards.some(c=>c.classList.contains('marked'))){
    const div=document.createElement('div');
    div.className='bmdiv flex items-center gap-3 text-[10px] uppercase tracking-widest text-zinc-400 dark:text-zinc-500 py-1';
    div.innerHTML='<span class="flex-1 border-t border-zinc-300 dark:border-zinc-700"></span><span>all results</span><span class="flex-1 border-t border-zinc-300 dark:border-zinc-700"></span>';
    results.insertBefore(div, firstPlain);
  }
}

async function search(){
  const t0 = performance.now();
  const query = q.value.trim();
  const proj = project.value;
  const lim = limit.value;
  const roles = selectedRoles().join(',');
  status.textContent = query ? `searching “${query}”…` : 'loading recent…';
  try{
    const url = `/api/search?q=${encodeURIComponent(query)}&project=${encodeURIComponent(proj)}&limit=${lim}&roles=${roles}`;
    const r = await fetch(url);
    let data = await r.json();
    status.textContent = query ? `found ${data.length} for “${query}”` : `recent ${data.length}`;
    const bmSet = new Set(getBM().map(b=>b.mid));
    const have = new Set(data.map(d=>d.messageID));
      const extra = getBM().filter(b=>!have.has(b.mid))
        .map(b=>({messageID:b.mid, sessionID:b.sid, title:b.title, project:b.project, role:b.role, time:b.time, snippet:b.snippet, context:b.context||''}))
      .sort((a,b)=>b.time-a.time);
    data = [...extra, ...data];
    data.sort((a,b)=>(bmSet.has(b.messageID)?1:0)-(bmSet.has(a.messageID)?1:0));
    results.innerHTML='';
    rendered.clear();
    if(!data.length){ empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    data.forEach((item)=>{
      const marked = bmSet.has(item.messageID);
      const projShort = (item.project||'').replace(/\\/g,'/').split('/').slice(-2).join('/') || item.project;
      const el=document.createElement('div');
      el.className='card relative bg-[#e4e8ed] dark:bg-zinc-800 rounded-2xl border border-zinc-200 dark:border-zinc-700 p-4 sm:p-5';
      el.innerHTML=`
        <button class="bm" data-mid="${item.messageID}" title="Bookmark this">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg>
        </button>
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="mb-1.5">
              <span class="text-[10px] px-1.5 py-0.5 rounded-full ${item.role==='assistant' ? 'bg-violet-600 dark:bg-violet-900/40 text-white dark:text-violet-300' : 'bg-zinc-600 dark:bg-zinc-700 text-white dark:text-zinc-200'}">${item.role==='assistant' ? 'agent' : 'user'}</span>
            </div>
            <div class="mb-1 flex gap-2">
              <span class="text-xs font-mono text-zinc-500 dark:text-zinc-400 w-28 shrink-0 pt-0.5">Session title:</span>
              <span class="text-[16px] font-semibold leading-tight dark:text-zinc-100 bg-transparent border border-zinc-800 dark:border-white/70 px-1.5 py-0.5 -ml-1.5 rounded-md inline-block" title="${item.title}">${item.title||'(untitled)'}</span>
            </div>
            <div class="mb-2 flex gap-2">
              <span class="text-xs font-mono text-zinc-500 dark:text-zinc-400 w-28 shrink-0">Folder:</span>
              <span class="text-xs text-zinc-500 dark:text-zinc-400">${projShort||'global'}</span>
            </div>
            <div class="mt-1 flex gap-2 text-xs text-zinc-500 dark:text-zinc-400">
              <span class="font-mono w-28 shrink-0">Session created:</span>
              <span>${fmtD(item.created)}</span>
            </div>
            <p class="mt-4 text-[13px] leading-relaxed text-zinc-700 dark:text-zinc-300 line-clamp-3">${highlight(item.snippet, query, item.context)}</p>
          </div>
        </div>
      `;
      rendered.set(item.messageID, item);
      paintBM(el.querySelector('.bm'), marked);
      if(marked) el.classList.add('marked');
      results.appendChild(el);
    });
    fixDivider();
    const dtMs = performance.now() - t0;
    msSamples.push(dtMs);
    if(msSamples.length > 20) msSamples.shift();
    const avgMs = msSamples.reduce((a,b)=>a+b,0) / msSamples.length;
    document.getElementById('ms').textContent = `${Math.round(avgMs)} ms avg`;

  }catch(e){ status.textContent='error'; console.error(e); }
}

const kwTip = document.createElement('div');
kwTip.id = 'kwTip';
kwTip.className = 'fixed z-50 hidden max-w-[min(440px,86vw)] max-h-[70vh] overflow-y-auto text-xs leading-relaxed px-3 py-2 rounded-xl shadow-xl border bg-zinc-900 text-zinc-100 border-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:border-zinc-300';
document.body.appendChild(kwTip);
results.addEventListener('mouseover', e=>{
  const m = e.target.closest('mark[data-tip]');
  if(!m){ kwTip.classList.add('hidden'); return; }
  kwTip.innerHTML = highlight(m.dataset.tip, q.value.trim());
  kwTip.classList.remove('hidden');
  const r = m.getBoundingClientRect();
  const w = kwTip.offsetWidth, h = kwTip.offsetHeight;
  kwTip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2)) + 'px';
  let tipTop = r.bottom + 8 + h > window.innerHeight ? r.top - h - 8 : r.bottom + 8;
  tipTop = Math.min(Math.max(8, tipTop), Math.max(8, window.innerHeight - h - 8));
  kwTip.style.top = tipTop + 'px';
});
results.addEventListener('mouseleave', e=>{
  if(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('#kwTip')) return;
  kwTip.classList.add('hidden');
});
kwTip.addEventListener('mouseleave', ()=>kwTip.classList.add('hidden'));

q.addEventListener('input', ()=> debounce(search, 220));
project.addEventListener('change', search);
limit.addEventListener('change', search);
roleUser.addEventListener('change', search);
roleAssistant.addEventListener('change', search);
results.addEventListener('click', e=>{
  const btn = e.target.closest('.bm');
  if(!btn) return;
  const item = rendered.get(btn.dataset.mid);
  if(!item) return;
  const nowMarked = toggleBM(item);
  paintBM(btn, nowMarked);
  const card = btn.closest('.card');
  if(card){
    card.classList.toggle('marked', nowMarked);
    if(nowMarked) results.prepend(card);
  }
  fixDivider();
});
document.addEventListener('keydown', e=>{ if(e.key==='/' && document.activeElement!==q){ e.preventDefault(); q.focus(); }});
document.getElementById('darkToggle').onclick=()=>{
  const isDark=document.documentElement.classList.toggle('dark');
  localStorage.setItem('searchpro-dark', isDark?'1':'0');
};

const modelsToggle = document.getElementById('modelsToggle');
const modelsBody = document.getElementById('modelsBody');
const modelsChevron = document.getElementById('modelsChevron');
const modelsBars = document.getElementById('modelsBars');
let modelsLoaded = false;
async function loadModels(){
  try{
    const r = await fetch('/api/models');
    const rows = await r.json();
    const top = rows.slice(0, 12);
    const rest = rows.slice(12);
    if(rest.length) top.push({model: `+${rest.length} more`, prompts: rest.reduce((a,b)=>a+b.prompts,0), cost: 0, other: true});
    const max = Math.max(1, ...top.map(t=>t.prompts));
    const total = rows.reduce((a,b)=>a+(b.prompts||0),0) || 1;
    modelsBars.innerHTML = '';
    top.forEach((t, i)=>{
      const pct = Math.max(2, Math.round(t.prompts / max * 100));
      const share = t.prompts / total * 100;
      const row = document.createElement('div');
      row.innerHTML = `
        <div class="flex items-baseline justify-between gap-2 text-xs">
          <span class="truncate ${t.other ? 'text-zinc-400' : 'font-medium'}">${t.model}</span>
          <span class="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">${t.prompts.toLocaleString('en-US')} prompts · ${share < 1 ? '<1' : Math.round(share)}%</span>
        </div>
        <div class="mt-1 h-3 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
          <div class="h-full rounded-full ${i===0 ? 'bg-zinc-700 dark:bg-zinc-200' : 'bg-zinc-400 dark:bg-zinc-500'}" style="width:${pct}%"></div>
        </div>`;
      modelsBars.appendChild(row);
    });
  }catch(e){ modelsBars.innerHTML = '<p class="text-xs text-zinc-400">failed to load</p>'; }
}
modelsToggle.addEventListener('click', ()=>{
  const open = modelsBody.classList.toggle('open');
  modelsChevron.style.transform = open ? 'rotate(180deg)' : '';
  localStorage.setItem('searchpro-models', open ? '1' : '0');
  if(open && !modelsLoaded){ modelsLoaded = true; loadModels(); }
});
if(localStorage.getItem('searchpro-models') === '1'){ modelsToggle.click(); }

try{ localStorage.setItem('searchpro-test','1'); localStorage.removeItem('searchpro-test'); }
catch(e){ status.textContent = 'browser storage blocked — bookmarks won\'t persist'; }
Promise.all([loadProjects(), loadStats()]).then(search);
q.focus();
</script>
</body>
</html>

"""

def open_db():
    # WAL-aware read-only: sees the latest committed frames without blocking the writer.
    # Do NOT use immutable=1 here — it pins reads to the last checkpoint and hides fresh WAL content.
    uri = pathlib.Path(DB).as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except:
        import shutil, tempfile
        tmp = os.path.join(tempfile.gettempdir(), "opencode_search.db")
        for suffix in ("", "-wal", "-shm"):
            src = DB + suffix
            if os.path.exists(src):
                shutil.copy2(src, tmp + suffix)
        con = sqlite3.connect(tmp, timeout=5)
    con.row_factory = sqlite3.Row
    return con

def query(q, project, limit, roles=("user",)):
    roles = tuple(r for r in (roles or ("user",)) if r in ("user", "assistant")) or ("user",)
    con = open_db()
    cur = con.cursor()
    placeholders = ",".join("?" for _ in roles)
    sql = f"""
    SELECT s.id as session_id, s.title as title, s.directory as directory,
           s.time_updated as time_updated, s.time_created as time_created,
           p.worktree as project, json_extract(pt.data,'$.text') as prompt,
           json_extract(m.data,'$.role') as role, m.id as message_id,
           m.time_created as msg_time
    FROM part pt
    JOIN message m ON m.id=pt.message_id
    JOIN session s ON s.id=pt.session_id
    LEFT JOIN project p ON p.id=s.project_id
    WHERE json_extract(m.data,'$.role') IN ({placeholders}) AND json_extract(pt.data,'$.type')='text' AND json_extract(pt.data,'$.text') IS NOT NULL
    """
    params=list(roles)
    if q:
        sql+=" AND lower(json_extract(pt.data,'$.text')) LIKE ?"
        params.append(f"%{q.lower()}%")
    if project:
        sql+=" AND (lower(p.worktree) LIKE ? OR lower(s.directory) LIKE ?)"
        pf=f"%{project.lower()}%"; params.extend([pf,pf])
    sql+=" ORDER BY s.time_updated DESC, m.time_created DESC LIMIT ?"
    params.append(int(limit)*3)
    cur.execute(sql, params)
    rows=cur.fetchall()
    out=[]; seen=set()
    q_lower = (q or "").lower()
    for r in rows:
        txt=r["prompt"] or ""
        key=(r["session_id"], r["role"], txt[:80])
        if key in seen: continue
        seen.add(key)
        # prefer directory over worktree "/"
        proj = r["directory"] or r["project"] or ""
        if r["project"] and r["project"]!="/" and r["project"].lower() not in (proj or "").lower():
            proj = f"{proj} ({r['project']})" if proj else r["project"]
        # center snippet on query if present, else first 220
        norm=" ".join(txt.split())
        if q_lower and q_lower in norm.lower():
            idx=norm.lower().find(q_lower)
            start=max(0, idx-100)
            end=min(len(norm), idx+len(q)+100)
            snippet=norm[start:end]
            if start>0: snippet="…"+snippet
            if end<len(norm): snippet=snippet+"…"
        else:
            snippet=norm
            if len(snippet)>220: snippet=snippet[:217]+"…"
        # wider hover context around the match (tooltip), capped
        if q_lower and q_lower in norm.lower():
            c_idx=norm.lower().find(q_lower)
            c_start=max(0, c_idx-300)
            c_end=min(len(norm), c_idx+len(q)+300)
            context=norm[c_start:c_end]
            if c_start>0: context="…"+context
            if c_end<len(norm): context=context+"…"
        else:
            context=norm[:600]
            if len(norm)>600: context=context+"…"
        t=r["time_updated"] or r["time_created"] or 0
        out.append({"messageID":r["message_id"], "sessionID":r["session_id"], "title":r["title"] or "(untitled)", "project":proj or "global", "snippet":snippet, "context":context, "time":int(t), "created":int(r["time_created"] or 0), "msgTime":int(r["msg_time"] or 0), "role":r["role"] or "user"})
        if len(out)>=int(limit): break
    con.close()
    return out

def list_projects():
    # Working folders sessions ran in (what opencode Ctrl+B groups by), not the project registry.
    con=open_db()
    cur=con.cursor()
    cur.execute("SELECT DISTINCT COALESCE(s.directory, p.worktree, 'global') as proj FROM session s LEFT JOIN project p ON p.id=s.project_id ORDER BY proj")
    rows=[r[0] for r in cur.fetchall() if r[0]]
    con.close()
    # dedupe, keep meaningful
    seen = []
    for p in rows:
        if p not in seen:
            seen.append(p)
    return seen[:60]

def model_stats():
    # User prompts grouped by each message's own model (exact), cost by session model (approx).
    con = open_db()
    cur = con.cursor()
    per = {}
    def key_of(prov, mid):
        return f"{prov or '?'} / {mid or '?'}"
    for prov, mid, n in cur.execute(
        """SELECT json_extract(m.data,'$.model.providerID'),
                  COALESCE(json_extract(m.data,'$.model.modelID'), json_extract(m.data,'$.model.id')),
                  COUNT(*)
           FROM message m
           WHERE json_extract(m.data,'$.role')='user'
           GROUP BY 1, 2"""):
        k = key_of(prov, mid)
        d = per.setdefault(k, {"model": k, "prompts": 0, "sessions": 0, "cost": 0.0})
        d["prompts"] = n
    for prov, mid, nsess, cost in cur.execute(
        """SELECT json_extract(model,'$.providerID'),
                  COALESCE(json_extract(model,'$.modelID'), json_extract(model,'$.id')),
                  COUNT(*), COALESCE(SUM(cost),0)
           FROM session GROUP BY 1, 2"""):
        k = key_of(prov, mid)
        d = per.setdefault(k, {"model": k, "prompts": 0, "sessions": 0, "cost": 0.0})
        d["sessions"] = nsess
        d["cost"] = round(cost or 0, 4)
    con.close()
    return sorted(per.values(), key=lambda d: -d["prompts"])

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path)
        qs=urllib.parse.parse_qs(parsed.query)
        if parsed.path=="/":
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.end_headers()
            self.wfile.write(get_html().encode())
            return
        if parsed.path=="/api/stats":
            mb = os.path.getsize(DB) / (1024*1024)
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.end_headers()
            self.wfile.write(json.dumps({"db_mb": round(mb), "db_path": DB}).encode())
            return
        if parsed.path=="/api/search":
            q=qs.get("q",[""])[0]
            proj=qs.get("project",[""])[0]
            lim=qs.get("limit",["20"])[0]
            roles_raw=qs.get("roles",["user"])[0]
            roles=tuple(r.strip() for r in roles_raw.split(",") if r.strip() in ("user","assistant")) or ("user",)
            data=query(q, proj, lim, roles)
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Cache-Control","no-store"); self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return
        if parsed.path=="/api/projects":
            data=list_projects()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return
        if parsed.path=="/api/models":
            data=model_stats()
            self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return
        self.send_response(404); self.end_headers()

if __name__=="__main__":
    # Auto-restart when web.py itself changes (index.html needs no restart — served from disk).
    # Disable with: python web.py --no-reload
    if "--no-reload" not in sys.argv:
        def _watch_self():
            try:
                last = pathlib.Path(__file__).stat().st_mtime
            except Exception:
                return
            while True:
                time.sleep(1.0)
                try:
                    cur = pathlib.Path(__file__).stat().st_mtime
                except Exception:
                    continue
                if cur != last:
                    print("\nweb.py changed — restarting…")
                    sys.stdout.flush()
                    os.execv(sys.executable, [sys.executable, str(pathlib.Path(__file__).resolve())] + [a for a in sys.argv[1:] if a != "--no-reload"])
        threading.Thread(target=_watch_self, daemon=True).start()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"OpenCode SearchPro -> http://127.0.0.1:{PORT}  (DB: {DB})")
        print(f"UI: {HTML_PATH} (edit + browser refresh, no restart needed)")
        print("Press Ctrl+C to stop")
        try: httpd.serve_forever()
        except KeyboardInterrupt: pass
